//! The sign-in gate: nothing is served to anyone the operator has not named.
//!
//! `frontage-api APP.py --auth google` puts four routes in front of the app — `/login`,
//! `/logout`, `/auth/google/start`, `/auth/google/callback` — and a middleware over
//! everything else: a request with a valid session passes, and one without it is a `303` to
//! the login page (or a bare `401` under `/api/`, where a browser redirect would only produce
//! a login page parsed as JSON). The gate sits above the static files too, which is the
//! entire point: a private site is a directory of prerendered HTML, and `ServeDir` would
//! otherwise hand it to anyone with the URL.
//!
//! **What it is not.** There are no users, no roles and no per-path rules: an allow-list of
//! email addresses either contains you or does not. `API.md` §5a is the decision and its
//! reasoning, including why this repository carries a flow the fleet already has once.
//!
//! # Configuration
//!
//! Every variable is read under `FRONTAGE_AUTH_*` first and `AXUM_OAUTH_*` second —
//! first-found-wins, never a union, because a union resurrects an address from a stale twin
//! after it was removed from the live one. The second namespace is what the fleet's deployed
//! env files and `LoadCredential=` lines already carry.
//!
//! | var | what |
//! |---|---|
//! | `…_GOOGLE_CLIENT_ID` | the OAuth client |
//! | `…_GOOGLE_CLIENT_SECRET` | its secret, read from `$CREDENTIALS_DIRECTORY` first so it never enters the environment |
//! | `…_BASE_URL` | the site's public origin. It settles the callback URL *and* whether cookies carry `Secure`, so the two cannot drift apart. **Unset means production** — dev opts out by setting it to `http://127.0.0.1:PORT` |
//! | `…_GOOGLE_REDIRECT_URI` | an override, for a callback that is not under the base |
//! | `…_ALLOWED_EMAILS` | who may sign in, comma separated. Empty is fatal at startup, not a site nobody can read |
//! | `…_SESSION_TTL_SECS` | session lifetime, default 30 days |
//! | `…_SECRET_FILE` | where the signing secret is persisted, default `.auth_secret` beside the app |

mod oidc;
mod session;

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use axum::body::Body;
use axum::extract::{Query, Request, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::middleware::Next;
use axum::response::{Html, IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use serde::Deserialize;

use oidc::{safe_return_to, Oidc};
use session::{persisted_secret, Session};

/// 30 days, the fleet's default: the claims carry an address the visitor already gave Google,
/// and the gate re-checks nothing per request, so this is the revocation window.
const DEFAULT_TTL: i64 = 30 * 24 * 3600;

/// Paths that answer without a session. `/login` and `/auth/` are the flow itself; the other
/// two are what a deploy's liveness and version probes ask for, and they must not be a
/// redirect to a login page.
const PUBLIC_EXACT: [&str; 4] = ["/login", "/logout", "/healthz", "/version"];
const PUBLIC_PREFIX: [&str; 1] = ["/auth/"];

/// The whole gate: the flow, the session, and the list of who may open it.
pub struct Auth {
    label: String,
    oidc: Oidc,
    session: Session,
    allowed: HashSet<String>,
}

impl Auth {
    /// Read the configuration, or say exactly what is missing and refuse to start.
    ///
    /// **Every failure here is fatal on purpose.** A server that starts without a client
    /// secret, or with an empty allow-list, is a private site that is either unreachable or
    /// unguarded, and both are worse than a process that will not come up.
    /// `dir` is where the secret lands by default and, in `--serve` mode, what is being
    /// served — which is why `served` is passed separately and checked against it.
    pub fn from_env(label: &str, dir: &Path, served: Option<&Path>) -> Result<Self, String> {
        let client_id = var("GOOGLE_CLIENT_ID").ok_or_else(|| missing("GOOGLE_CLIENT_ID"))?;
        let client_secret = secret_var(label, "GOOGLE_CLIENT_SECRET").ok_or_else(|| missing("GOOGLE_CLIENT_SECRET"))?;
        let base = var("BASE_URL").map(|b| b.trim_end_matches('/').to_string());
        let redirect_uri = match (var("GOOGLE_REDIRECT_URI"), &base) {
            (Some(explicit), _) => explicit,
            (None, Some(base)) => format!("{base}/auth/google/callback"),
            (None, None) => return Err(missing("BASE_URL")),
        };
        let allowed: HashSet<String> = var("ALLOWED_EMAILS")
            .unwrap_or_default()
            .split(',')
            .map(|e| e.trim().to_ascii_lowercase())
            .filter(|e| !e.is_empty())
            .collect();
        if allowed.is_empty() {
            return Err(format!(
                "{}: no address may sign in, so nobody could read this site. Set it to a comma-separated list.",
                missing("ALLOWED_EMAILS")
            ));
        }
        let ttl = var("SESSION_TTL_SECS").and_then(|t| t.parse().ok()).unwrap_or(DEFAULT_TTL);
        let secret_file = var("SECRET_FILE").map(PathBuf::from).unwrap_or_else(|| dir.join(".auth_secret"));
        // ⚠ The signing secret must not live inside the directory being served. Two ways that
        // ends badly and both are silent: `ServeDir` hands the file to anyone with a session,
        // who can then mint one for anybody; and a deploy rsyncs that tree with `--delete`, so
        // the secret changes under the running process and every visitor is signed out.
        if let Some(served) = served {
            if secret_file.starts_with(served) {
                return Err(format!(
                    "the session secret would live at {}, inside the directory being served. \
                     Set FRONTAGE_AUTH_SECRET_FILE to a path outside it.",
                    secret_file.display()
                ));
            }
        }
        let secret = persisted_secret(&secret_file);
        // Secure cookies unless the base URL is explicitly plain http (local dev, where a
        // Secure cookie would never come back and sign-in could not work at all). Unset reads
        // as production: the two failure directions are not symmetric.
        let secure = match std::env::var("AUTH_COOKIE_SECURE").ok().as_deref() {
            Some("false") | Some("0") => false,
            Some(_) => true,
            None => base.as_deref().is_none_or(|b| !b.starts_with("http://")),
        };
        Ok(Self {
            oidc: Oidc::new(client_id, client_secret, redirect_uri, label, secret.as_bytes(), secure),
            session: Session::new(format!("{label}_session"), ttl, secret.as_bytes(), secure),
            allowed,
            label: label.to_string(),
        })
    }

    /// What to print at startup, so an operator can see what the gate believes.
    pub fn summary(&self) -> String {
        format!("google sign-in for {} address(es), callback {}", self.allowed.len(), self.oidc.redirect_uri())
    }

    fn allows(&self, email: &str) -> bool {
        self.allowed.contains(&email.trim().to_ascii_lowercase())
    }
}

/// The four routes plus the gate, wrapped around an app's own router.
pub fn wrap(router: Router, auth: Arc<Auth>) -> Router {
    // The four routes carry their own state and are `with_state`d back to `()` before the
    // merge, so the app's router stays exactly the shape `hive-server` takes.
    let flow = Router::new()
        .route("/login", get(login))
        .route("/logout", get(logout))
        .route("/auth/google/start", get(start))
        .route("/auth/google/callback", get(callback))
        .with_state(auth.clone());
    router.merge(flow).layer(axum::middleware::from_fn_with_state(auth, gate))
}

/// A valid session passes anything; otherwise the flow's own paths and the probes pass,
/// `/api/*` gets a bare `401`, and everything else is sent to sign in.
async fn gate(State(auth): State<Arc<Auth>>, request: Request, next: Next) -> Response {
    if auth.session.present(request.headers()) {
        return next.run(request).await;
    }
    let path = request.uri().path();
    if PUBLIC_EXACT.contains(&path) || PUBLIC_PREFIX.iter().any(|p| path.starts_with(p)) {
        return next.run(request).await;
    }
    if path.starts_with("/api/") {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let target = request.uri().path_and_query().map(|pq| pq.as_str()).unwrap_or("/");
    see_other(&format!("/login?return_to={}", urlencoding::encode(target)))
}

#[derive(Deserialize)]
struct ReturnTo {
    return_to: Option<String>,
}

/// The page an unauthenticated visitor lands on: one button, and nothing else to get wrong.
async fn login(State(auth): State<Arc<Auth>>, headers: HeaderMap, Query(q): Query<ReturnTo>) -> Response {
    let target = safe_return_to(q.return_to.as_deref(), "/");
    // Already signed in: the login page is not somewhere to sit.
    if auth.session.present(&headers) {
        return see_other(&target);
    }
    Html(page::login(&auth.label, &format!("/auth/google/start?return_to={}", urlencoding::encode(&target)))).into_response()
}

async fn logout(State(auth): State<Arc<Auth>>) -> Response {
    let mut response = see_other("/login");
    response.headers_mut().append(header::SET_COOKIE, auth.session.clear());
    response
}

/// Step 1. The bounce first: the state cookie must be set on the host the callback will
/// arrive at, or it is simply not sent back (the `localhost` against `127.0.0.1` dev trap).
async fn start(State(auth): State<Arc<Auth>>, headers: HeaderMap, Query(q): Query<ReturnTo>) -> Response {
    let here = headers.get(header::HOST).and_then(|v| v.to_str().ok());
    if let Some(dest) = canonical_bounce(auth.oidc.redirect_uri(), here, &format!("/auth/google/start?return_to={}", urlencoding::encode(&safe_return_to(q.return_to.as_deref(), "/")))) {
        return see_other(&dest);
    }
    match auth.oidc.start(q.return_to.as_deref()) {
        Ok(start) => {
            let mut response = see_other(&start.authorize_url);
            response.headers_mut().append(header::SET_COOKIE, start.set_cookie);
            response
        }
        Err(e) => {
            eprintln!("frontage-api: sign-in could not start: {e}");
            notice(&e)
        }
    }
}

#[derive(Deserialize)]
struct CallbackQuery {
    code: Option<String>,
    state: Option<String>,
    error: Option<String>,
}

/// Step 2. Verified identity, then the one authorization question, then a session.
async fn callback(State(auth): State<Arc<Auth>>, headers: HeaderMap, Query(q): Query<CallbackQuery>) -> Response {
    let identity = match auth.oidc.complete(&headers, q.code.as_deref(), q.state.as_deref(), q.error.as_deref()).await {
        Ok(identity) => identity,
        Err(e) => {
            eprintln!("frontage-api: sign-in failed: {e}");
            return with_cleared_state(&auth, notice(&e));
        }
    };
    if !auth.allows(&identity.email) {
        eprintln!("frontage-api: sign-in denied for {} (not on the list)", identity.email);
        let body = page::notice(
            &auth.label,
            "Not authorized",
            &format!("{} is not on this site's list.", page::escape(&identity.email)),
        );
        return with_cleared_state(&auth, Html(body).into_response());
    }
    println!("frontage-api: sign-in for {}", identity.email);
    let Some(cookie) = auth.session.mint(&identity.email) else {
        return (StatusCode::INTERNAL_SERVER_ERROR, "could not mint a session").into_response();
    };
    let mut response = see_other(&identity.return_to);
    response.headers_mut().append(header::SET_COOKIE, cookie);
    response.headers_mut().append(header::SET_COOKIE, auth.oidc.clear_state_cookie());
    response
}

/// Clear the state cookie on any terminal answer, so a failed flow leaves nothing behind.
fn with_cleared_state(auth: &Auth, mut response: Response) -> Response {
    response.headers_mut().append(header::SET_COOKIE, auth.oidc.clear_state_cookie());
    response
}

fn notice(e: &oidc::Error) -> Response {
    Html(page::notice("", e.title(), &page::escape(&e.user_message()))).into_response()
}

fn see_other(location: &str) -> Response {
    Response::builder()
        .status(StatusCode::SEE_OTHER)
        .header(header::LOCATION, location)
        .body(Body::empty())
        .unwrap_or_else(|_| StatusCode::INTERNAL_SERVER_ERROR.into_response())
}

/// Where to bounce to before starting, when this request arrived on a host that is not the
/// one the callback will come back to. `None` when we are already in the right place, or when
/// the redirect URI is not a host we can compare against.
fn canonical_bounce(redirect_uri: &str, host: Option<&str>, path_and_query: &str) -> Option<String> {
    let (scheme, rest) = redirect_uri.split_once("://")?;
    let canonical = rest.split('/').next()?;
    let here = host?;
    (here != canonical).then(|| format!("{scheme}://{canonical}{path_and_query}"))
}

/// `FRONTAGE_AUTH_{suffix}`, else `AXUM_OAUTH_{suffix}`. First-found-wins, never a union.
fn var(suffix: &str) -> Option<String> {
    ["FRONTAGE_AUTH", "AXUM_OAUTH"]
        .into_iter()
        .find_map(|prefix| std::env::var(format!("{prefix}_{suffix}")).ok())
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

/// Like [`var`], but a systemd credential beats the environment — where a secret is readable
/// through `/proc/<pid>/environ` and inherited by every child. Per namespace, not per
/// mechanism: the canonical name wins outright, however it is supplied.
///
/// ⚠ **Two spellings, because the fleet has two.** A unit written with explicit
/// `LoadCredential=` lines names the credential for the variable (`axum_oauth_…`, lower case,
/// which is what the deployed apps carry); a unit on `ImportCredential=<app>.*` — what
/// `hive-deploy` renders for an isolated app — presents it as `<app>.<KEY>`, keeping its case.
/// Reading only one of them is a secret that is definitely there and definitely not found.
fn secret_var(label: &str, suffix: &str) -> Option<String> {
    ["FRONTAGE_AUTH", "AXUM_OAUTH"].into_iter().find_map(|prefix| {
        let key = format!("{prefix}_{suffix}");
        if let Some(dir) = std::env::var_os("CREDENTIALS_DIRECTORY") {
            let dir = Path::new(&dir);
            for name in [key.to_ascii_lowercase(), format!("{label}.{key}")] {
                if let Ok(s) = std::fs::read_to_string(dir.join(name)) {
                    let s = s.trim_end_matches(['\n', '\r']).to_string();
                    if !s.is_empty() {
                        return Some(s);
                    }
                }
            }
        }
        std::env::var(&key).ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty())
    })
}

fn missing(suffix: &str) -> String {
    format!("--auth google needs FRONTAGE_AUTH_{suffix} (or AXUM_OAUTH_{suffix})")
}

/// The two pages the gate serves itself. Deliberately inline and dependency-free: they have
/// to render before a visitor is allowed to fetch anything at all, including a stylesheet.
mod page {
    pub fn escape(s: &str) -> String {
        s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
    }

    const STYLE: &str = "*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;\
font:16px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;background:#fff;color:#18181b}\
main{max-width:24rem;padding:2rem;text-align:center}h1{font-size:1.25rem;font-weight:600;margin:0 0 .5rem}\
p{color:#71717a;margin:0 0 1.5rem}a.button{display:inline-flex;align-items:center;gap:.625rem;\
padding:.625rem 1.25rem;border:1px solid #d4d4d8;border-radius:.5rem;text-decoration:none;color:inherit;\
font-weight:500}a.button:hover{background:#f4f4f5}a.quiet{color:#71717a;font-size:.875rem}\
@media(prefers-color-scheme:dark){body{background:#09090b;color:#fafafa}p{color:#a1a1aa}\
a.button{border-color:#3f3f46}a.button:hover{background:#18181b}}";

    /// Google's mark, inline: an artifact behind a sign-in cannot fetch an image before it.
    const MARK: &str = r##"<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#4285F4" d="M45.1 24.5c0-1.6-.1-3.2-.4-4.7H24v9h11.8c-.5 2.7-2 5-4.4 6.6v5.5h7.1c4.2-3.8 6.6-9.5 6.6-16.4z"/><path fill="#34A853" d="M24 46c5.9 0 10.9-2 14.5-5.3l-7.1-5.5c-2 1.3-4.5 2.1-7.4 2.1-5.7 0-10.5-3.8-12.2-9H4.5v5.7C8.1 41.2 15.5 46 24 46z"/><path fill="#FBBC05" d="M11.8 28.3c-.4-1.3-.7-2.7-.7-4.3s.3-3 .7-4.3v-5.7H4.5C2.9 17.2 2 20.5 2 24s.9 6.8 2.5 10l7.3-5.7z"/><path fill="#EA4335" d="M24 10.7c3.2 0 6.1 1.1 8.4 3.3l6.3-6.3C34.9 4.1 29.9 2 24 2 15.5 2 8.1 6.8 4.5 13.7l7.3 5.7c1.7-5.2 6.5-9 12.2-9z"/></svg>"##;

    fn shell(title: &str, body: &str) -> String {
        format!(
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">\
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\
<meta name=\"color-scheme\" content=\"light dark\"><meta name=\"robots\" content=\"noindex\">\
<title>{}</title><style>{STYLE}</style></head><body><main>{body}</main></body></html>",
            escape(title)
        )
    }

    pub fn login(label: &str, start_href: &str) -> String {
        let name = if label.is_empty() { "This site".to_string() } else { escape(label) };
        shell(
            &format!("Sign in — {}", if label.is_empty() { "frontage" } else { label }),
            &format!(
                "<h1>{name}</h1><p>This site is private. Sign in to continue.</p>\
<a class=\"button\" href=\"{}\">{MARK} Sign in with Google</a>",
                escape(start_href)
            ),
        )
    }

    /// A terminal state: a failed flow, or an address that is not on the list.
    pub fn notice(label: &str, title: &str, body_html: &str) -> String {
        let _ = label;
        shell(title, &format!("<h1>{}</h1><p>{body_html}</p><a class=\"quiet\" href=\"/login\">← Back to sign in</a>", escape(title)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_bounce_moves_a_request_onto_the_callbacks_host_and_only_then() {
        let uri = "http://127.0.0.1:8008/auth/google/callback";
        assert_eq!(
            canonical_bounce(uri, Some("localhost:8008"), "/auth/google/start"),
            Some("http://127.0.0.1:8008/auth/google/start".to_string())
        );
        assert_eq!(canonical_bounce(uri, Some("127.0.0.1:8008"), "/auth/google/start"), None);
        assert_eq!(canonical_bounce(uri, None, "/auth/google/start"), None);
    }

    #[test]
    fn the_login_page_carries_the_button_and_asks_not_to_be_indexed() {
        let html = page::login("governor", "/auth/google/start?return_to=%2Fplan%2F");
        assert!(html.contains("Sign in with Google"));
        assert!(html.contains("return_to=%2Fplan%2F"));
        assert!(html.contains("name=\"robots\" content=\"noindex\""));
        // An address on a notice page is escaped, not interpolated raw.
        assert!(page::notice("", "Not authorized", &page::escape("<b>a@x.com</b>")).contains("&lt;b&gt;"));
    }
}
