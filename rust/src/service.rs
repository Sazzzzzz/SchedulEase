use once_cell::sync::Lazy;
use reqwest::Url;

static LOGIN_URL: Lazy<Url> =
    Lazy::new(|| Url::parse("https://iam.nankai.edu.cn").expect("Invalid LOGIN_URL"));
static EAMIS_URL: Lazy<Url> =
    Lazy::new(|| Url::parse("https://eamis.nankai.edu.cn").expect("Invalid EAMIS_URL"));

static LOGIN_API: Lazy<Url> = Lazy::new(|| {
    LOGIN_URL
        .join("/api/v1/login?os=web")
        .expect("Failed to join LOGIN_API")
});
static SITE_URL: Lazy<Url> = Lazy::new(|| {
    EAMIS_URL
        .join("/eams/homeExt.action")
        .expect("Failed to join SITE_URL")
});
static PROFILE_URL: Lazy<Url> = Lazy::new(|| {
    EAMIS_URL
        .join("/eams/stdElectCourse.action")
        .expect("Failed to join PROFILE_URL")
});
static COURSE_INFO_URL: Lazy<Url> = Lazy::new(|| {
    EAMIS_URL
        .join("/eams/stdElectCourse!data.action")
        .expect("Failed to join COURSE_INFO_URL")
});
static ELECT_URL: Lazy<Url> = Lazy::new(|| {
    EAMIS_URL
        .join("/eams/stdElectCourse!batchOperator.action")
        .expect("Failed to join ELECT_URL")
});

pub struct EamisService {
    client: reqwest::Client,
    account: String,
    encrypted_password: String,
}
impl EamisService {
    pub fn new(account: &str, encrypted_password: &str) -> Self {
        let client = reqwest::Client::builder()
            .cookie_store(true)
            .build()
            .expect("Failed to build reqwest client");
        EamisService {
            client,
            account: account.to_string(),
            encrypted_password: encrypted_password.to_string(),
        }
    }
}
