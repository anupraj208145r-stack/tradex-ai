# TradeX AI Android

This is an Android WebView companion app for the live TradeX AI paper-trading website:
https://tradex-ai-production.up.railway.app/

## Build APK
GitHub Actions builds a debug APK when this branch is pushed or when the workflow is manually run:
1. Open the repository's Actions tab.
2. Select **Build TradeX AI Android APK**.
3. Select **Run workflow** if it has not started automatically.
4. Download the **TradeX-AI-Android-debug** artifact from the completed run.

The APK is a WebView client. It requires an internet connection and uses the production website and its existing Supabase sign-in. Email/password and phone OTP are the intended in-app sign-in paths. Google OAuth opens the external browser; return-to-app OAuth handoff is not implemented in this first build.

This first version is not a standalone offline trading engine and does not execute real broker orders. It is a mobile wrapper around the existing paper-only web application.
