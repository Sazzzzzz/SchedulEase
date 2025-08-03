use schedulease::config;
use schedulease::service::EamisService;
fn main() {
    let config = config::load_config().expect("Failed to load config");
    let mut service = EamisService::new(&config);
    service.initial_connection().expect("Failed to connect to EAMIS service");
    service.login().expect("Login failed");
}
