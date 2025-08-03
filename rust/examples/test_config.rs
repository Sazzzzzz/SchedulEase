#[cfg(test)]
mod tests {

    use schedulease::config::encrypt;
    #[test]
    fn test_encrypt_known_value() {
        let encrypted = encrypt("password");
        assert_eq!(encrypted, "ed1c3b662478e45f85088d3d8598d9b3");
    }

    #[test]
    fn test_encrypt_different_inputs() {
        let a = encrypt("password123");
        let b = encrypt("Password123");
        assert_ne!(a, b);
    }

    #[test]
    fn test_encrypt_consistency() {
        let input = "test_string";
        let first = encrypt(input);
        let second = encrypt(input);
        assert_eq!(first, second);
    }
}

fn main() {}
