use crate::config::Config;
use encoding_rs::GBK;
use once_cell::sync::Lazy;
use reqwest::{
    blocking::{Client, RequestBuilder, Response},
    header::{HeaderMap, HeaderName, HeaderValue},
    Url,
};
use std::str::FromStr; // Required for HeaderName::from_str

static LOGIN_URL: Lazy<Url> =
    Lazy::new(|| Url::parse("https://iam.nankai.edu.cn").expect("Invalid LOGIN_URL"));
static EAMIS_URL: Lazy<Url> =
    Lazy::new(|| Url::parse("https://eamis.nankai.edu.cn").expect("Invalid EAMIS_URL"));

static LOGIN_API: Lazy<Url> = Lazy::new(|| LOGIN_URL.join("/api/v1/login?os=web").unwrap());
static SITE_URL: Lazy<Url> = Lazy::new(|| EAMIS_URL.join("/eams/homeExt.action").unwrap());
static PROFILE_URL: Lazy<Url> =
    Lazy::new(|| EAMIS_URL.join("/eams/stdElectCourse.action").unwrap());
static COURSE_INFO_URL: Lazy<Url> =
    Lazy::new(|| EAMIS_URL.join("/eams/stdElectCourse!data.action").unwrap());
static ELECT_URL: Lazy<Url> = Lazy::new(|| {
    EAMIS_URL
        .join("/eams/stdElectCourse!batchOperator.action")
        .unwrap()
});

#[derive(thiserror::Error, Debug)]
pub enum ServiceError {
    #[error("Network or connection error: {0}")]
    ConnectionError(#[from] reqwest::Error),

    #[error("Login failed: {msg}")]
    LoginError { msg: String },

    #[error("Failed to parse response: {msg}")]
    ParseError { msg: String },

    #[error("Course election failed: {msg}")]
    ElectionError { msg: String },
}

pub struct EamisService {
    client: Client,
    headers: HeaderMap,

    account: String,
    encrypted_password: String,
}

impl EamisService {
    // The constructor can now fail, so it should return a Result
    pub fn new(config: &Config) -> Self {
        let mut default_headers = HeaderMap::new();
        let headers = HeaderMap::new();

        for (key, value) in &config.headers {
            let header_name =
                HeaderName::from_str(key).expect(&format!("Invalid header name: {}", key));
            let header_value = HeaderValue::from_str(value)
                .expect(&format!("Invalid header value for {}: {}", key, value));
            default_headers.insert(header_name, header_value);
        }
        let client = Client::builder()
            .cookie_store(true)
            .redirect(reqwest::redirect::Policy::limited(10))
            .default_headers(default_headers) // Use the newly created HeaderMap
            .build()
            .expect("Failed to build reqwest client");

        EamisService {
            client,
            headers,
            account: config.user.account.clone(),
            encrypted_password: config.user.encrypted_password.clone(),
        }
    }
    /// A helper method to append headers to get request.
    pub fn get(&self, url: &Url) -> RequestBuilder {
        self.client.get(url.clone()).headers(self.headers.clone())
    }

    /// A helper method to append headers to post request.
    pub fn post(&self, url: &Url) -> RequestBuilder {
        self.client.post(url.clone()).headers(self.headers.clone())
    }

    /// Test the initial connection to the EAMIS service. Raises `ConnectionError` if the connection fails.
    ///
    /// This is a single method that must be invoked manually to ensure the service is reachable.
    pub fn initial_connection(&mut self) -> Result<(), ServiceError> {
        let response = self.get(&EAMIS_URL).send()?;
        response.error_for_status()?;

        self.headers.insert(
            HeaderName::from_static("sec-fetch-site"),
            HeaderValue::from_static("same-origin"),
        );
        Ok(())
    }

    /// Login to the EAMIS service
    pub fn login(&mut self) -> Result<(), ServiceError> {
        // Redirect to site
        let prelogin_response = self
            .get(&SITE_URL)
            .send()
            .unwrap()
            .error_for_status()
            .map_err(ServiceError::ConnectionError)
            .unwrap();
        // API call to login
        let csrf_token = prelogin_response
            .cookies()
            .find(|c| c.name() == "csrf-token")
            .map(|c| c.value().to_string())
            .unwrap_or_else(|| "".to_string());
        let login_headers = HeaderMap::from_iter(vec![
            (
                HeaderName::from_static("cache-control"),
                HeaderValue::from_static("no-cache"),
            ),
            (
                HeaderName::from_static("content-type"),
                HeaderValue::from_static("application/json"),
            ),
            (
                HeaderName::from_static("csrf-token"),
                HeaderValue::from_str(&csrf_token).unwrap(),
            ),
            (
                HeaderName::from_static("sec-fetch-dest"),
                HeaderValue::from_static("empty"),
            ),
            (
                HeaderName::from_static("sec-fetch-mode"),
                HeaderValue::from_static("cors"),
            ),
            (
                HeaderName::from_static("sec-fetch-site"),
                HeaderValue::from_static("same-origin"),
            ),
            (
                HeaderName::from_static("referer"),
                HeaderValue::from_str(prelogin_response.url().as_str()).unwrap(),
            ),
        ]);

        let login_response = self
            .post(&LOGIN_API)
            .json(&serde_json::json!({
                "login_scene": "feilian",
                "account_type": "userid",
                "account": self.account,
                "password": self.encrypted_password,
            }))
            .headers(login_headers)
            .send()?
            .error_for_status()?;

        let content: serde_json::Value =
            login_response
                .json()
                .map_err(|e| ServiceError::ParseError {
                    msg: format!("JSON parsing error: {}", e),
                })?;

        let code = content["code"].as_i64().unwrap_or(-1);
        let message = content["message"].as_str().unwrap_or("Unknown error");

        match code {
            0 => Ok(()),
            10110001 => Err(ServiceError::LoginError {
                msg: format!(
                    "Login failed: {}. Please check your account and password.",
                    message
                ),
            }),
            40000 => Err(ServiceError::LoginError {
                msg: format!(
                    "Login failed: {}。 Parameter error, likely due to a change in the API format.",
                    message
                ),
            }),
            _ => Err(ServiceError::LoginError {
                msg: format!("Login failed with code {}: {}", code, message),
            }),
        }
    }
}
