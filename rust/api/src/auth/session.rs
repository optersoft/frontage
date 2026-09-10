//! The session cookie: an HS256 JWT of `{sub, exp}`, and the secret that signs it.
//!
//! The claims are the authenticated email and an expiry, and nothing else — an address the
//! visitor already typed into Google, so a leaked cookie carries nothing transferable. The
//! gate checks the signature and `exp`; it does not re-consult the allow-list per request,
//! which is what bounds a revocation to the session's lifetime and is why the default is 30
//! days rather than a year.

use std::path::Path;

use axum::http::{header, HeaderMap, HeaderValue};
use jsonwebtoken::{decode, encode, Algorithm, DecodingKey, EncodingKey, Header, Validation};
use serde::{Deserialize, Serialize};

use super::oidc::now;

#[derive(Serialize, Deserialize)]
struct Claims {
    sub: String,
    exp: i64,
}

/// Mints and verifies this app's session cookie.
#[derive(Clone)]
pub struct Session {
    name: String,
    ttl: i64,
    secret: Vec<u8>,
    secure: bool,
}

impl Session {
    pub fn new(name: String, ttl: i64, secret: &[u8], secure: bool) -> Self {
        Self { name, ttl, secret: secret.to_vec(), secure }
    }

    /// The `Set-Cookie` that signs `email` in for this session's lifetime.
    pub fn mint(&self, email: &str) -> Option<HeaderValue> {
        let claims = Claims { sub: email.to_string(), exp: now() + self.ttl };
        let jwt = encode(&Header::new(Algorithm::HS256), &claims, &EncodingKey::from_secret(&self.secret)).ok()?;
        self.header(&jwt, self.ttl)
    }

    /// The `Set-Cookie` that ends the session.
    pub fn clear(&self) -> HeaderValue {
        self.header("", 0).expect("an empty cookie is header-safe")
    }

    /// Is there a valid, unexpired session on this request?
    pub fn present(&self, headers: &HeaderMap) -> bool {
        self.email(headers).is_some()
    }

    /// Who this request is, if it is anyone.
    pub fn email(&self, headers: &HeaderMap) -> Option<String> {
        let raw = cookie(headers, &self.name)?;
        let mut validation = Validation::new(Algorithm::HS256);
        validation.validate_aud = false;
        validation.required_spec_claims.clear();
        validation.required_spec_claims.insert("exp".to_string());
        // No leeway, for the same reason the state cookie has none: this process signed the
        // cookie, so there is no clock to be skewed against and the default 60 seconds would
        // only extend every session past the expiry it was minted with.
        validation.leeway = 0;
        decode::<Claims>(&raw, &DecodingKey::from_secret(&self.secret), &validation).ok().map(|d| d.claims.sub)
    }

    fn header(&self, value: &str, max_age: i64) -> Option<HeaderValue> {
        let secure = if self.secure { " Secure;" } else { "" };
        HeaderValue::from_str(&format!("{}={value}; Path=/; HttpOnly; SameSite=Lax;{secure} Max-Age={max_age}", self.name)).ok()
    }
}

/// One cookie out of a request's `Cookie` header.
pub fn cookie(headers: &HeaderMap, name: &str) -> Option<String> {
    headers.get(header::COOKIE).and_then(|v| v.to_str().ok()).and_then(|raw| {
        raw.split(';').find_map(|part| {
            let (k, v) = part.trim().split_once('=')?;
            (k == name).then(|| v.to_string())
        })
    })
}

/// The HS256 signing secret (hex): the persisted file when it holds one, else 32 fresh random
/// bytes, persisted `0600` and returned.
///
/// It is a file and not an env var on purpose — a secret in the environment is readable
/// through `/proc/<pid>/environ` and inherited by every child. Persisted, because a secret
/// regenerated on boot signs everybody out on every deploy, and this server hot-swaps.
pub fn persisted_secret(path: &Path) -> String {
    if let Ok(s) = std::fs::read_to_string(path) {
        let s = s.trim().to_string();
        if !s.is_empty() {
            return s;
        }
    }
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("the OS CSPRNG is unavailable");
    let hex: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if std::fs::write(path, &hex).is_ok() {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
        }
    } else {
        eprintln!("frontage-api: could not persist the session secret at {} — a restart signs everyone out", path.display());
    }
    hex
}

#[cfg(test)]
mod tests {
    use super::*;

    fn with_cookie(value: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(header::COOKIE, HeaderValue::from_str(value).unwrap());
        headers
    }

    #[test]
    fn a_minted_cookie_verifies_and_names_its_user() {
        let s = Session::new("governor_session".into(), 3600, b"secret", true);
        let set = s.mint("a@optersoft.com").unwrap();
        let jwt = set.to_str().unwrap().split(';').next().unwrap();
        assert_eq!(s.email(&with_cookie(jwt)).as_deref(), Some("a@optersoft.com"));
    }

    #[test]
    fn another_secret_and_an_expired_claim_are_both_nobody() {
        let s = Session::new("governor_session".into(), 3600, b"secret", true);
        let jwt = s.mint("a@optersoft.com").unwrap().to_str().unwrap().split(';').next().unwrap().to_string();
        let other = Session::new("governor_session".into(), 3600, b"different", true);
        assert!(!other.present(&with_cookie(&jwt)));
        // A cookie whose TTL has run out is not a session either — and `jsonwebtoken` would
        // have said it was, on its default 60 seconds of leeway, which is why there is none.
        let stale = Session::new("governor_session".into(), -10, b"secret", true);
        let jwt = stale.mint("a@optersoft.com").unwrap().to_str().unwrap().split(';').next().unwrap().to_string();
        assert!(!s.present(&with_cookie(&jwt)));
    }

    #[test]
    fn cookies_are_read_out_of_a_crowded_header() {
        let headers = with_cookie("theme=dark; governor_session=abc; other=1");
        assert_eq!(cookie(&headers, "governor_session").as_deref(), Some("abc"));
        assert_eq!(cookie(&headers, "missing"), None);
        // A name that is a prefix of another cookie's must not answer for it.
        assert_eq!(cookie(&with_cookie("governor_session_1=x"), "governor_session"), None);
    }

    #[test]
    fn a_session_cookie_is_httponly_lax_and_rooted_at_the_site() {
        let s = Session::new("governor_session".into(), 3600, b"secret", true);
        let set = s.mint("a@optersoft.com").unwrap();
        let set = set.to_str().unwrap();
        assert!(set.contains("Path=/") && set.contains("HttpOnly") && set.contains("SameSite=Lax") && set.contains("Secure"), "{set}");
        assert!(s.clear().to_str().unwrap().contains("Max-Age=0"));
    }
}
