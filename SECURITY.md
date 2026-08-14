# Security Policy

## Overview

UniFi Protect App Store (Nexus Vision Marketplace) is designed as an on-premises AI vision platform for security cameras and NVRs. This document describes the security model, threat boundaries, and how to report vulnerabilities.

## Threat Model

### Deployment Context

This platform is designed for deployment on **trusted on-premises networks** alongside UniFi Protect NVRs and cameras. The typical deployment:

- Runs inside a Docker container on local infrastructure (Jetson, RTX server, or x86 host)
- Connects to UniFi Protect and UniFi Access controllers via local network
- Processes RTSP video streams from cameras on the same network segment
- Does NOT expose cameras or video streams to the internet
- May serve web interfaces (landing page, storefront, API) on internal networks

### Trust Boundaries

**Trusted:**
- The Docker host and container runtime
- The local network segment where cameras/NVR reside
- Administrators with physical or SSH access to the host
- Users with access to the admin token (`VISION_ADMIN_TOKEN`)

**Untrusted:**
- Any network traffic from outside the local network
- Marketplace function modules from third parties (if modified)
- User-provided configuration (sites.yaml, environment variables)

### Key Security Considerations

1. **Video Privacy**: All video processing happens on-premises. Video never leaves your network unless you configure external webhooks.

2. **Camera/NVR Access**: The platform requires credentials to UniFi Protect and optionally UniFi Access. These credentials should use **dedicated read-only accounts** with minimal privileges.

3. **API Security**: Admin endpoints (`/api/subscriptions` list/patch) require `X-Admin-Token` header authentication. Public endpoints (signup, status check) do not require authentication by design.

4. **SSL/TLS Verification**: By default, the platform disables SSL certificate verification for UniFi controllers (common for self-signed certs on local appliances). **This creates a man-in-the-middle risk on untrusted networks.**

## Security Best Practices

### 1. Network Isolation

- Deploy on a **trusted internal network segment** with cameras and NVRs
- Use VLANs or network segmentation to isolate camera networks from guest/public networks
- If exposing the web interface, use a reverse proxy (nginx, Traefik) with HTTPS and authentication
- **Do NOT expose port 8090 directly to the internet**

### 2. Credential Management

- Use **dedicated service accounts** for UniFi Protect (read-only local user)
- Store credentials in `.env` file with restrictive permissions (`chmod 600 .env`)
- Never commit `.env` or any file containing real credentials to version control
- Rotate credentials periodically, especially `VISION_ADMIN_TOKEN`
- Use strong, randomly generated tokens:
  ```bash
  # Generate secure tokens
  openssl rand -hex 32
  ```

### 3. SSL/TLS Configuration

**Risk**: `.env.example` defaults to `UNIFI_PROTECT_VERIFY_SSL=false` and `UNIFI_ACCESS_VERIFY_SSL=false` for ease of setup with self-signed certificates.

**Recommended for production:**
1. Enable SSL verification: set both to `true`
2. Install trusted CA certificates or add your UniFi controller's CA cert to the container's trust store
3. Alternatively, use a reverse proxy with valid certificates

**If you must disable SSL verification** (self-signed certs on isolated network):
- Ensure the camera/NVR network is physically isolated and trusted
- Document this decision in your deployment notes
- Monitor network traffic for anomalies

### 4. Access Control

- Limit access to the Docker host (SSH keys, firewall rules)
- Protect the `VISION_ADMIN_TOKEN` — this grants full control over subscription data
- Consider IP allowlisting for the admin API endpoints if exposed
- Review container logs regularly for unauthorized access attempts

### 5. Data Retention

- Snapshots and clips are stored in `VISION_DATA` (default: `./data` mounted volume)
- Implement retention policies to limit storage of sensitive images
- Secure the data directory with appropriate filesystem permissions
- Include the data directory in backup encryption if backing up the host

### 6. Webhook Security

- When using `EXTRA_WEBHOOK_URL`, ensure the destination is trusted (Slack, Teams, internal systems)
- Avoid forwarding sensitive video frames to untrusted external services
- Use HTTPS URLs for webhook targets
- Consider webhook signature verification if implementing custom receivers

### 7. Container Security

- Run the container as a **non-root user** (see Dockerfile USER directive)
- Keep base images updated (rebuild periodically for security patches)
- Use Docker security features: read-only root filesystem where possible, drop capabilities
- Enable Docker Content Trust for image verification

### 8. Marketplace Functions

- Review any custom or third-party marketplace functions before loading them
- Functions run in-process and have full Python execution context
- The loader validates manifests but does not sandbox function code
- Only load functions from trusted sources

## Known Limitations

1. **No built-in authentication for public endpoints**: The signup and status endpoints are intentionally public. If you need authentication, use a reverse proxy with basic auth or OAuth.

2. **Admin token is bearer-style**: The `X-Admin-Token` header uses a simple bearer token. Protect it like a password. Consider rotating it after any exposure.

3. **SQLite database has no encryption**: Subscription data is stored in `data/subscriptions.db` in plaintext. Encrypt the host volume if required by compliance.

4. **No rate limiting**: The API does not implement rate limiting. Use a reverse proxy (nginx, Traefik) to add rate limiting if exposing endpoints.

5. **Door unlock endpoint has minimal validation**: `/unlock/{door_id}` does not require authentication. This is by design for integration with intercom systems, but means any client with network access can trigger unlocks. **Implement network-level access control** if using this feature.

## Illinois BIPA Compliance

This platform is designed to comply with the Illinois Biometric Information Privacy Act (BIPA):

- **No face recognition or biometric identification**
- Detectors use pose estimation (skeletons), object detection, license plates, and counting only
- Video frames may be retained briefly for alerting but are not used for biometric databases
- Deployment is on-premises; no biometric data is transmitted to cloud services

Customers in Illinois or other jurisdictions with biometric privacy laws should:
- Review local regulations and consult legal counsel
- Implement appropriate signage and notice requirements
- Configure retention policies to minimize stored imagery
- Use "skeleton mode" where applicable to discard video after pose extraction

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

**Email**: security@nexusct.com  
**Subject**: UniFi Protect App Store Security Issue

Please include:
- Description of the vulnerability
- Steps to reproduce (proof-of-concept if applicable)
- Potential impact and affected versions
- Any suggested mitigations

We will acknowledge receipt within 48 hours and provide a timeline for fixes. We appreciate responsible disclosure and will credit reporters (with permission) in release notes.

**Please do NOT**:
- Open public GitHub issues for security vulnerabilities
- Include exploit code in public forums before the issue is patched
- Test vulnerabilities against production systems you do not own

## Security Updates

Security fixes are released as patches to the `main` branch and tagged as releases. Subscribe to GitHub releases or watch the repository to receive notifications.

For critical vulnerabilities, we will:
1. Release a patch within 7 days
2. Publish a security advisory on GitHub
3. Notify known enterprise deployments via email

## Additional Resources

- [OWASP Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [UniFi Protect Security Best Practices](https://help.ui.com/hc/en-us/articles/360012192813)

---

**Last Updated**: August 2026  
**Maintainer**: Nexus Communications Technology, Schaumburg, IL
