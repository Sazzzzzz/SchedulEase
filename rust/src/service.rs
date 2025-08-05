use crate::config::Config;
use once_cell::sync::Lazy;
use reqwest::{
    blocking::{Client, RequestBuilder},
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

    postlogin_url: Option<Url>,
    profiles: Option<Vec<Profile>>,
}

#[derive(Clone, Debug)]
pub struct Profile {
    pub title: String,
    pub url: Url,
    pub id: String,
}

#[derive(PartialEq)]
pub enum Operation {
    Elect,
    Cancel,
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
            postlogin_url: None,
            profiles: None,
        }
    }

    // ---- Helper Functions ----
    /// A helper method to append headers to get request.
    pub fn get(&self, url: &Url) -> RequestBuilder {
        self.client.get(url.clone()).headers(self.headers.clone())
    }

    /// A helper method to append headers to post request.
    pub fn post(&self, url: &Url) -> RequestBuilder {
        self.client.post(url.clone()).headers(self.headers.clone())
    }
    /// Helper function to create a timestamp in milliseconds.
    pub fn create_timestamp() -> String {
        let now = std::time::SystemTime::now();
        let duration = now.duration_since(std::time::UNIX_EPOCH).unwrap();
        (duration.as_secs() * 1000 + duration.subsec_millis() as u64).to_string()
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

    // ---- Cached Properties ----

    /// Returns the post-login URL.
    ///
    /// Similar to cached property design in Python
    pub fn postlogin_url(&mut self) -> Url {
        if let Some(url) = &self.postlogin_url {
            return url.clone();
        }
        // If postlogin_url is not set, we need to login first
        let login_url = self.login().unwrap();
        self.postlogin_url = Some(login_url.clone());
        login_url
    }
    /// Login to the EAMIS service
    pub fn login(&mut self) -> Result<Url, ServiceError> {
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
        // TODO: Replace print here to actual logic
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
                    "Login failed: {}. Parameter error, likely due to a change in the API format.",
                    message
                ),
            }),
            _ => Err(ServiceError::LoginError {
                msg: format!("Login failed with code {}: {}", code, message),
            }),
        }?;
        let link_str =
            content["data"]["next"]["link"]
                .as_str()
                .ok_or_else(|| ServiceError::ParseError {
                    msg: "Link field is not a string".to_string(),
                })?;
        let link = LOGIN_URL
            .join(link_str)
            .map_err(|e| ServiceError::ParseError {
                msg: format!(
                    "Failed to parse next link: {}. Likely due to a change in the API format.",
                    e
                ),
            })?;
        let postlogin_response = self
            .get(&link)
            .send()
            .map_err(ServiceError::ConnectionError)?;
        println!("Login successful. Redirecting to: {}", link);
        Ok(postlogin_response.url().clone())
    }

    /// Course Profiles
    pub fn profiles(&mut self) -> &Vec<Profile> {
        // We avoid match here to avoid borrowing issues
        if self.profiles.is_none() {
            self.profiles = Some(self.get_profiles().unwrap());
        }
        self.profiles.as_ref().unwrap()
    }

    /// Fetch all election categories available to the user.
    pub fn get_profiles(&mut self) -> Result<Vec<Profile>, ServiceError> {
        let postlogin_url = self.postlogin_url();

        let course_elect_menu_response = self
            .get(&PROFILE_URL)
            .header("Referer", postlogin_url.as_str())
            .header("X-Requested-With", "XMLHttpRequest")
            .query(&[("_", EamisService::create_timestamp())])
            .send()?;

        let response_url = course_elect_menu_response.url().clone();
        let content = course_elect_menu_response.text()?;
        let document = scraper::Html::parse_document(&content);

        // Check if we got redirected to the wrong page
        if response_url.path().contains("home") {
            return Err(ServiceError::ElectionError {
                msg: "Request was redirected to home page instead of course selection page."
                    .to_string(),
            });
        }

        if content.contains("无法选课") || content.contains("未到选课时间") {
            return Err(ServiceError::ElectionError {
                msg: "Course election menu is currently not available..".to_string(),
            });
        }

        let elect_index_selector = scraper::Selector::parse("div[id^='electIndexNotice']").unwrap();
        let selection_divs = document.select(&elect_index_selector);
        let mut course_categories = Vec::new();
        // TODO: Fix this long selector process
        for div in selection_divs {
            if let Some(title_element) = div.select(&scraper::Selector::parse("h3").unwrap()).next()
            {
                let title = title_element.inner_html().trim().to_string();
                if let Some(link_element) = div
                    .select(&scraper::Selector::parse("a[href]").unwrap())
                    .next()
                {
                    if let Some(href) = link_element.value().attr("href") {
                        let profile_id = href.split('=').last().unwrap_or("");
                        if let Ok(url) = EAMIS_URL.join(href) {
                            course_categories.push(Profile {
                                title,
                                url,
                                id: profile_id.to_string(),
                            });
                        }
                    }
                }
            }
        }

        Ok(course_categories)
    }

    pub fn elect_course(
        &mut self,
        course_id: &str,
        profile_id: &str,
        operation: Operation,
    ) -> Result<(), ServiceError> {
        let opt = match operation {
            Operation::Elect => "elect",
            Operation::Cancel => "cancel",
        };

        let elect_response = self
            .post(&ELECT_URL)
            .header("Referer", self.postlogin_url().as_str())
            .header("X-Requested-With", "XMLHttpRequest")
            .query(&[("_", EamisService::create_timestamp())])
            .form(&[
                ("optype", opt),
                ("operator0", &format!("{}:{}:0", course_id, opt)),
                ("lesson0", course_id),
                ("profileId", profile_id),
            ])
            .send()?;

        let content = elect_response.text()?;
        println!("Elect response: {}", content);
        if content.contains("选课成功") {
            Ok(())
        } else if content.contains("当前选课不开放") {
            Err(ServiceError::ElectionError {
                msg: "Course election is currently not open.".to_string(),
            })
        } else if content.contains("已经选过") {
            Err(ServiceError::ElectionError {
                msg: format!("Course {} is already elected.", course_id),
            })
        } else if content.contains("计划外名额已满") {
            Err(ServiceError::ElectionError {
                msg: format!(
                    "Course {} is considered as extra and has no available spots.",
                    course_id
                ),
            })
        } else if content.contains("退课成功") && operation == Operation::Cancel {
            Ok(())
        } else {
            Err(ServiceError::ElectionError {
                msg: format!(
                    "Failed to elect or cancel course {}. Response: {}",
                    course_id, content
                ),
            })
        }
    }
}
