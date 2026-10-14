# Google sign-in setup and release

Email/password login remains available. Google sign-in code is implemented, but real Google sign-in cannot run until the OAuth clients below exist. No client secret belongs in the app.

## Google Cloud setup

Use one Google Cloud project owned by the team. Configure Google Auth Platform branding, audience and contact details. Request only basic identity (openid, email, profile); this feature does not need Gmail access. Add test users while the consent app is in testing.

Create these OAuth clients:

1. **Web application**: add the actual deployed frontend origin under Authorized JavaScript origins; add localhost origins only for local testing. The web app uses Google Identity Services popup sign-in. This client ID is also the audience requested by native sign-in and verified by the backend.
2. **Android**: package `com.adchronotype.app`. Register the SHA-1 from Play Console's **App integrity → App signing key certificate** for Play-installed apps. Register a separate Android client for a different EAS/development signing certificate if testing builds signed with that key. The Android client ID does not go into an environment variable; the package/certificate registration is what Google checks.
3. **iOS**: bundle ID `com.adchronotype.app`. Set the public iOS client ID below; `app.config.js` derives and registers its reversed URL scheme automatically. No Firebase project or Google service configuration files are required for this integration.

## Configuration

Frontend build environment (local `.env` for development; EAS production environment for native builds; frontend host build environment for web):

```text
EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID=<web client ID ending in .apps.googleusercontent.com>
EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID=<iOS client ID ending in .apps.googleusercontent.com>
```

Backend environment:

```text
GOOGLE_WEB_CLIENT_ID=<the exact same web client ID>
```

The public client IDs are identifiers, not client secrets. Never set a client secret under `EXPO_PUBLIC_*`. The backend refuses Google sign-in if its audience is missing. The frontend shows an unavailable message until configured.

## Backend release order

1. Install updated requirements.
2. Back up the production database following the hosting team's normal procedure.
3. Run `alembic upgrade head` against the intended database. This includes caregiver nap duration revision `20261007_0011`, followed by Google subject revision `20261012_0012`.
4. Deploy backend with `GOOGLE_WEB_CLIENT_ID` configured, then build and release the frontend with the public client IDs.
5. Build a new native app; an OTA JavaScript update or Expo Go cannot add the native Google SDK.

## Account behavior

`POST /auth/google` accepts an ID token (and optionally `current_password` when linking an existing account). Google verifies its signature, expiration, issuer and audience; the backend requires a verified email and stores Google's stable `sub` identifier. Normal app access/refresh tokens are returned through the existing auth flow.

A matching email alone does not link an existing account. The user enters their existing app password in the Login screen, then chooses Google again. Linking retains the same account ID, patient records and password. Subsequent Google sign-ins use the stored Google subject. Disabled accounts remain blocked. A new Google user gets a random, unknown password hash; they may use the existing Forgot Password flow to establish an app password if they want one.

Existing consent and welcome flows still run after Google sign-in. No Google access or refresh tokens are requested or stored on the server.

## Verification before public release

- New Google account signs in and reaches the existing consent/onboarding flow.
- Existing account cannot link without its password; correct password links to the same account and retains records.
- Password login still works after linking; Google works after logout and app restart.
- Cancellation returns to Login without an error; offline/service failure leaves password login available.
- Test the Play-installed Android build, not only a build signed with the upload key.
- Confirm the web origin and iOS callback on actual devices once credentials exist.
- Review the app's privacy disclosure for Google identity handling.
- Before enabling Google in the App Store release, address Apple's guideline 4.8 requirement for an equivalent privacy-preserving login option (normally Sign in with Apple), unless a documented exception applies. Email/password alone does not supply its private-email feature. Sign in with Apple is not implemented in this change.

## Local checks

Frontend: `npm run typecheck`, `node --test tests/lead-feedback.test.mjs`, `npx expo export --platform all`.

Backend (disposable database configuration):

```sh
DATABASE_URL=sqlite:////tmp/adc-test-unused.db JWT_SECRET_KEY=unit-test-only-secret python -m pytest tests/test_google_auth.py tests/test_care_recommendations.py -q
```

The tests override database sessions with an in-memory database and do not connect to production. Google verifier tests include locally signed valid, expired, altered and wrong-audience tokens; live Google account authorization remains untested until credentials exist.

References:
- https://docs.expo.dev/guides/google-authentication/
- https://react-native-google-signin.github.io/docs/setting-up/expo
- https://developers.google.com/identity/sign-in/web/backend-auth
- https://developer.apple.com/app-store/review/guidelines/#login-services
