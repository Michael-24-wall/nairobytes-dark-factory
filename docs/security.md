# Security Boundary

- The browser never receives database credentials or service secrets.
- The asset endpoint accepts only a small allowlist of image/PDF MIME types and limits files to 10 MB.
- Uploaded filenames are reduced to their basename and stored under a generated UUID filename.
- Asset serving checks the resolved path remains inside the configured workspace root.
- GitHub, deployment credentials, authentication providers, environment variables, and admin authorization are not configured in the current slice.
- No arbitrary command execution endpoint exists.

Project authorization is not implemented yet; the current local project API should be treated as a development-only boundary until authentication and backend access control are added.