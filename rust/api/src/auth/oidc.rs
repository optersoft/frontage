//! The authorization-code flow with PKCE, Google only, ending at a verified [`Identity`].
//!
//! Two calls. [`Oidc::start`] mints the CSRF state, the OIDC nonce and the PKCE verifier,
//! seals all three (plus `return_to`) into a short-lived HS256-signed `HttpOnly` cookie, and
//! answers the authorize URL. [`Oidc::complete`] unseals that cookie, matches the state,
//! exchanges the code server-to-server with `client_secret` + `code_verifier`, and verifies
//! the `id_token`'s RS256 signature against Google's published JWKS — plus `aud`, `iss`,
//! `exp` and the `nonce` — before answering an identity.
//!
//! ⚠ **This is a second implementation of a flow the fleet has in one crate**, `axum-oauth`,
//! and `API.md` §5a is where that was decided and why: this repository is public and its CI
//! resolves the whole cargo workspace, so a path dependency on a private sibling breaks every
//! run of it. The decisions here are that crate's, deliberately — the state cookie scoped to
//! `/auth/google`, `leeway = 0` on our own cookie and the provider's default on theirs, the
//! forced JWKS refetch on a `kid` miss, `email_verified` accepted as a bool or the string
//! Google used to send. When one of them turns out to be wrong, both files change.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use axum::http::{HeaderMap, HeaderValue};
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use jsonwebtoken::jwk::JwkSet;
use jsonwebtoken::{decode, decode_header, encode, Algorithm, DecodingKey, EncodingKey, Header, Validation};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::session::cookie;

/// Long enough for a slow consent screen, short enough to bound replay.
const STATE_TTL: i64 = 600;
/// Google rotates its signing keys on the order of a day, with a published overlap.
const JWKS_TTL: Duration = Duration::from_secs(3600);

const AUTHORIZE_URL: &str = "https://accounts.google.com/o/oauth2/v2/auth";
const TOKEN_URL: &str = "https://oauth2.googleapis.com/token";
const JWKS_URL: &str = "https://www.googleapis.com/oauth2/v3/certs";
const ISSUERS: [&str; 2] = ["accounts.google.com", "https://accounts.google.com"];
const SCOPES: &str = "openid email profile";

/// The client for one app. Cheap to clone; the `reqwest::Client` inside pools connections.
#[derive(Clone)]
pub struct Oidc {
    client_id: String,
    client_secret: String,
    redirect_uri: String,
    state_cookie: String,
    signing_key: Vec<u8>,
    secure: bool,
    http: reqwest::Client,
}

/// What [`Oidc::start`] produces: where to send the browser, and the cookie that rides along.
pub struct Start {
    pub authorize_url: String,
    pub set_cookie: HeaderValue,
}

/// A verified end user. Identity only — whether they may *read* anything is the gate's call.
pub struct Identity {
    pub email: String,
    /// Carried through the flow in the signed cookie, re-validated as a same-origin path.
    pub return_to: String,
}

/// Everything that can end a sign-in. `user_message` is deliberately vague on the
/// security-relevant checks: the detail goes to the log, not to whoever is trying them.
#[derive(Debug)]
pub enum Error {
    Cancelled(String),
    MissingCode,
    MissingState,
    InvalidState,
    StateMismatch,
    NonceMismatch,
    Exchange(String),
    IdToken(String),
    EmailNotVerified,
    NoEmail,
    Sign(String),
}

impl Error {
    pub fn title(&self) -> &'static str {
        match self {
            Error::Cancelled(_) => "Sign-in cancelled",
            Error::EmailNotVerified | Error::NoEmail => "Sign-in incomplete",
            _ => "Sign-in failed",
        }
    }

    pub fn user_message(&self) -> String {
        match self {
            Error::Cancelled(_) => "The sign-in was cancelled before it finished.".into(),
            Error::EmailNotVerified => "That Google account has no verified email address.".into(),
            Error::NoEmail => "That Google account did not return an email address.".into(),
            // Everything else is a state, signature or exchange failure. A visitor cannot act
            // on the difference and an attacker should not learn it; try again is the advice.
            _ => "Something went wrong signing in. Please try again.".into(),
        }
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Cancelled(e) => write!(f, "the provider cancelled: {e}"),
            Error::MissingCode => write!(f, "the callback carried no code"),
            Error::MissingState => write!(f, "the state cookie was not sent back"),
            Error::InvalidState => write!(f, "the state cookie did not verify"),
            Error::StateMismatch => write!(f, "the state parameter did not match the cookie"),
            Error::NonceMismatch => write!(f, "the id_token's nonce did not match the cookie"),
            Error::Exchange(e) => write!(f, "code exchange failed: {e}"),
            Error::IdToken(e) => write!(f, "id_token: {e}"),
            Error::EmailNotVerified => write!(f, "email_verified is not true"),
            Error::NoEmail => write!(f, "no email claim"),
            Error::Sign(e) => write!(f, "signing the state cookie failed: {e}"),
        }
    }
}

/// What rides in the state cookie: CSRF state, nonce, PKCE verifier, and where to land.
#[derive(Serialize, Deserialize)]
struct StateClaims {
    s: String,
    n: String,
    v: String,
    r: String,
    exp: i64,
}

#[derive(Deserialize)]
struct TokenResponse {
    id_token: String,
}

/// The claims we read out of a verified `id_token`. `aud`/`iss`/`exp` are enforced by the
/// validator, so they are not here.
#[derive(Deserialize)]
struct RawClaims {
    #[serde(default)]
    nonce: Option<String>,
    #[serde(default)]
    email: Option<String>,
    #[serde(default)]
    email_verified: Option<serde_json::Value>,
}

impl Oidc {
    pub fn new(client_id: String, client_secret: String, redirect_uri: String, label: &str, signing_key: &[u8], secure: bool) -> Self {
        Self {
            state_cookie: format!("{label}_google_oauth"),
            client_id,
            client_secret,
            redirect_uri,
            signing_key: signing_key.to_vec(),
            secure,
            http: reqwest::Client::new(),
        }
    }

    pub fn redirect_uri(&self) -> &str {
        &self.redirect_uri
    }

    /// Step 1 — the authorize redirect, and the state cookie that must accompany it.
    pub fn start(&self, return_to: Option<&str>) -> Result<Start, Error> {
        let csrf = random_b64(24);
        let nonce = random_b64(24);
        let verifier = random_b64(48);
        let challenge = URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()));
        let claims = StateClaims {
            s: csrf.clone(),
            n: nonce.clone(),
            v: verifier,
            r: safe_return_to(return_to, "/"),
            exp: now() + STATE_TTL,
        };
        let jwt = encode(&Header::new(Algorithm::HS256), &claims, &EncodingKey::from_secret(&self.signing_key))
            .map_err(|e| Error::Sign(e.to_string()))?;
        let params: Vec<(&str, &str)> = vec![
            ("client_id", &self.client_id),
            ("redirect_uri", &self.redirect_uri),
            ("response_type", "code"),
            ("scope", SCOPES),
            ("state", &csrf),
            ("nonce", &nonce),
            ("code_challenge", &challenge),
            ("code_challenge_method", "S256"),
            ("prompt", "select_account"),
            ("access_type", "online"),
        ];
        Ok(Start { authorize_url: url_with_query(AUTHORIZE_URL, &params), set_cookie: self.state_cookie_header(&jwt, STATE_TTL) })
    }

    /// Step 2 — the callback's query and the request's cookies, to a verified identity.
    pub async fn complete(&self, headers: &HeaderMap, code: Option<&str>, state: Option<&str>, error: Option<&str>) -> Result<Identity, Error> {
        if let Some(e) = error {
            return Err(Error::Cancelled(e.to_string()));
        }
        let (Some(code), Some(state_param)) = (code, state) else {
            return Err(Error::MissingCode);
        };
        // The signed cookie is the only thing binding this callback to the start that began it.
        let raw = cookie(headers, &self.state_cookie).ok_or(Error::MissingState)?;
        let st = self.verify_state(&raw).ok_or(Error::InvalidState)?;
        if st.s != state_param {
            return Err(Error::StateMismatch);
        }
        let id_token = self.exchange_code(code, &st.v).await?;
        let claims = self.verify_id_token(&id_token).await?;
        // The nonce binds the token to *this* attempt. It is request-specific, so the
        // validator cannot check it — we do, against the value sealed in the cookie.
        if claims.nonce.as_deref() != Some(st.n.as_str()) {
            return Err(Error::NonceMismatch);
        }
        if !verified(&claims.email_verified) {
            return Err(Error::EmailNotVerified);
        }
        let email = claims
            .email
            .as_deref()
            .map(|e| e.trim().to_ascii_lowercase())
            .filter(|e| !e.is_empty())
            .ok_or(Error::NoEmail)?;
        // The email is the identity this server keeps: there are no user rows for a `sub` to
        // key, and the allow-list is addresses. Google's `sub` would matter the day there are.
        Ok(Identity { email, return_to: safe_return_to(Some(&st.r), "/") })
    }

    /// Expire the state cookie — append it to the callback's response either way, so a failed
    /// flow leaves nothing behind.
    pub fn clear_state_cookie(&self) -> HeaderValue {
        self.state_cookie_header("", 0)
    }

    fn state_cookie_header(&self, value: &str, max_age: i64) -> HeaderValue {
        let secure = if self.secure { " Secure;" } else { "" };
        // ⚠ `Path=/auth/google` and the callback path are one decision: a callback registered
        // anywhere else never receives this cookie, and the flow ends at "state missing".
        HeaderValue::from_str(&format!(
            "{}={value}; Path=/auth/google; HttpOnly; SameSite=Lax;{secure} Max-Age={max_age}",
            self.state_cookie
        ))
        .expect("the state cookie is header-safe")
    }

    fn verify_state(&self, token: &str) -> Option<StateClaims> {
        let mut v = Validation::new(Algorithm::HS256);
        v.validate_aud = false;
        v.required_spec_claims.clear();
        v.required_spec_claims.insert("exp".to_string());
        // `jsonwebtoken` allows 60s of `exp` leeway for clock skew between issuer and
        // verifier. Here we are both — this process minted the cookie minutes ago — so the
        // skew is zero and leeway would only widen the replay window past the TTL. The
        // id_token's leeway stays at the default: that clock is Google's.
        v.leeway = 0;
        decode::<StateClaims>(token, &DecodingKey::from_secret(&self.signing_key), &v).ok().map(|d| d.claims)
    }

    async fn exchange_code(&self, code: &str, verifier: &str) -> Result<String, Error> {
        let response = self
            .http
            .post(TOKEN_URL)
            .form(&[
                ("grant_type", "authorization_code"),
                ("code", code),
                ("redirect_uri", &self.redirect_uri),
                ("client_id", &self.client_id),
                ("client_secret", &self.client_secret),
                ("code_verifier", verifier),
            ])
            .send()
            .await
            .map_err(|e| Error::Exchange(e.to_string()))?;
        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(Error::Exchange(format!("{status} {body}")));
        }
        let token: TokenResponse = response.json().await.map_err(|e| Error::Exchange(format!("decode token response: {e}")))?;
        Ok(token.id_token)
    }

    /// RS256 against Google's JWKS, plus `aud` (our client id), `iss` and `exp`.
    ///
    /// OIDC §3.1.3.7 would allow skipping the signature on a direct server-to-server TLS
    /// channel; verifying is cheap defence in depth, and keeps a forged token unusable even
    /// if the egress path is not what we think it is.
    async fn verify_id_token(&self, token: &str) -> Result<RawClaims, Error> {
        let header = decode_header(token).map_err(|e| Error::IdToken(format!("header: {e}")))?;
        if header.alg != Algorithm::RS256 {
            return Err(Error::IdToken(format!("unexpected alg {:?}", header.alg)));
        }
        let kid = header.kid.ok_or_else(|| Error::IdToken("no `kid`".into()))?;
        // Serve the cached set; on a `kid` miss force one refetch, because that is exactly
        // what a key rotated in since the last fetch looks like.
        let mut set = self.jwks(false).await?;
        if find(&set, &kid).is_none() {
            set = self.jwks(true).await?;
        }
        let jwk = find(&set, &kid).ok_or_else(|| Error::IdToken(format!("no JWK for kid {kid}")))?;
        let key = DecodingKey::from_jwk(jwk).map_err(|e| Error::IdToken(format!("decoding key: {e}")))?;
        let mut validation = Validation::new(Algorithm::RS256);
        validation.set_audience(&[&self.client_id]);
        validation.set_issuer(&ISSUERS);
        decode::<RawClaims>(token, &key, &validation).map(|d| d.claims).map_err(|e| Error::IdToken(e.to_string()))
    }

    /// The JWKS, from the process-wide cache unless `force`.
    ///
    /// The guard is cloned out and dropped before the network `await`: a `std::Mutex` must
    /// never be held across a suspension point.
    async fn jwks(&self, force: bool) -> Result<Arc<JwkSet>, Error> {
        static CACHE: OnceLock<Mutex<HashMap<String, (Instant, Arc<JwkSet>)>>> = OnceLock::new();
        let cache = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
        if !force {
            let hit = cache.lock().unwrap().get(JWKS_URL).cloned();
            if let Some((at, set)) = hit {
                if at.elapsed() < JWKS_TTL {
                    return Ok(set);
                }
            }
        }
        let set: JwkSet = self
            .http
            .get(JWKS_URL)
            .send()
            .await
            .and_then(|r| r.error_for_status())
            .map_err(|e| Error::IdToken(format!("fetch jwks: {e}")))?
            .json()
            .await
            .map_err(|e| Error::IdToken(format!("decode jwks: {e}")))?;
        let set = Arc::new(set);
        cache.lock().unwrap().insert(JWKS_URL.to_string(), (Instant::now(), set.clone()));
        Ok(set)
    }
}

fn find<'a>(set: &'a JwkSet, kid: &str) -> Option<&'a jsonwebtoken::jwk::Jwk> {
    set.find(kid)
}

/// Google has sent `email_verified` as a bool and, historically, as the string `"true"`.
fn verified(value: &Option<serde_json::Value>) -> bool {
    match value {
        Some(serde_json::Value::Bool(b)) => *b,
        Some(serde_json::Value::String(s)) => s == "true",
        _ => false,
    }
}

/// Only a same-origin path survives: `//evil.com` and `https://evil.com` are open redirects,
/// so anything that is not a single leading `/` collapses to the default.
pub fn safe_return_to(raw: Option<&str>, default: &str) -> String {
    raw.filter(|r| r.starts_with('/') && !r.starts_with("//"))
        .map(str::to_string)
        .unwrap_or_else(|| default.to_string())
}

/// The CSRF state, the nonce and the PKCE verifier all come from here, so it is the OS
/// CSPRNG and never a seeded PRNG. `getrandom` fails only when the OS entropy source is
/// unavailable, which is not a condition to paper over with a weak fallback.
fn random_b64(bytes: usize) -> String {
    let mut buf = vec![0u8; bytes];
    getrandom::fill(&mut buf).expect("the OS CSPRNG is unavailable");
    URL_SAFE_NO_PAD.encode(buf)
}

pub fn now() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0)
}

fn url_with_query(base: &str, params: &[(&str, &str)]) -> String {
    let mut out = String::with_capacity(base.len() + 96);
    out.push_str(base);
    for (i, (k, v)) in params.iter().enumerate() {
        out.push(if i == 0 { '?' } else { '&' });
        out.push_str(&urlencoding::encode(k));
        out.push('=');
        out.push_str(&urlencoding::encode(v));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn client() -> Oidc {
        Oidc::new("cid".into(), "secret".into(), "https://governor.optersoft.com/auth/google/callback".into(), "governor", b"k", true)
    }

    #[test]
    fn start_carries_pkce_and_state_and_the_cookie_is_scoped_to_the_callback() {
        let start = client().start(Some("/plan/")).unwrap();
        assert!(start.authorize_url.starts_with(AUTHORIZE_URL));
        assert!(start.authorize_url.contains("code_challenge_method=S256"));
        assert!(start.authorize_url.contains("client_id=cid"));
        let set = start.set_cookie.to_str().unwrap();
        assert!(set.starts_with("governor_google_oauth="));
        assert!(set.contains("Path=/auth/google"), "{set}");
        assert!(set.contains("HttpOnly") && set.contains("Secure"), "{set}");
    }

    #[test]
    fn the_state_cookie_round_trips_and_keeps_the_return_path() {
        let c = client();
        let jwt = c.start(Some("/dafo/")).unwrap().set_cookie.to_str().unwrap()
            .split(';').next().unwrap().split_once('=').unwrap().1.to_string();
        let st = c.verify_state(&jwt).expect("our own cookie verifies");
        assert_eq!(st.r, "/dafo/");
        // Another app's secret must not open it: one deployment's cookie is inert in the next.
        let other = Oidc::new("cid".into(), "s".into(), "u".into(), "governor", b"other", true);
        assert!(other.verify_state(&jwt).is_none());
    }

    #[test]
    fn open_redirects_collapse_to_the_default() {
        for evil in ["//evil.com", "https://evil.com", "evil.com"] {
            assert_eq!(safe_return_to(Some(evil), "/"), "/");
        }
        assert_eq!(safe_return_to(Some("/plan/?x=1"), "/"), "/plan/?x=1");
        assert_eq!(safe_return_to(None, "/"), "/");
    }

    #[test]
    fn email_verified_is_a_bool_or_the_string_google_used_to_send() {
        assert!(verified(&Some(serde_json::json!(true))));
        assert!(verified(&Some(serde_json::json!("true"))));
        assert!(!verified(&Some(serde_json::json!(false))));
        assert!(!verified(&None));
    }
}
