# Railway deployment — Student Consultation Scheduler

The app is **Python standard library + SQLite**. Docker and Railway are configured. The HTML/CSS/JS interface and all six accounts are preserved. The six account passwords are stored only as salted scrypt hashes inside the seeding code; the existing passwords you provided still work.

## Will I need to pay?
New Railway accounts normally start in a **30-day trial with $5 one-time credits**; Railway documents that a credit card is not required for the trial. After the trial Railway has a **$0/month Free plan with $1 monthly non-rollover credit**, subject to resource usage and availability; this is not a guarantee of a continuously running free site. Review billing and estimated usage in your Railway account. Data on trial-created volumes may be deleted 30 days after trial credits expire if not moved to an eligible plan—back it up before then.

## Deploy step by step

1. Create a **PRIVATE** GitHub repository (the project contains institutional IDs and school emails). Upload **the files INSIDE this project folder**, not the parent ZIP/folder. Avoid checking in `data/` or any SQLite database; `.gitignore` is included.
2. Sign in at https://railway.com using GitHub. A new account should enter the trial automatically; you do **not** need to purchase Hobby to try.
3. Create **New Project → Deploy from GitHub repo**, select your private repo and allow Railway repository access. The included `Dockerfile` and `railway.json` build and start the Python server (no pip packages or npm required).
4. **Add a persistent volume to the Python service** (service canvas → right-click service → Attach Volume, or service settings → Volumes); set its **mount path to `/data`**. This is ESSENTIAL. Railway injects `RAILWAY_VOLUME_MOUNT_PATH` and the application writes `consultations.sqlite` there, preserving bookings after redeploy. The Free/Trial volume limit is currently 0.5 GB.
5. In the service **Settings → Networking → Public Networking**, click **Generate Domain**. No custom domain is needed. The application listens on Railway's injected `PORT` and host `0.0.0.0` automatically.
6. If the service started before the volume was attached, **redeploy** it once afterward. Wait for the Railway build/deploy status to be healthy. Open `https://YOUR-DOMAIN.up.railway.app/api/health` and expect `{"status":"ok","database":"SQLite"}`, then open the domain root to sign in.
7. Test: sign in as a student, create a future consultation, sign in as the selected instructor in an incognito browser, approve it, change instructor availability, and confirm the status notification reaches the student. Restart/redeploy and verify the booking remains; this checks the mounted volume.

### Troubleshooting

- **Application failed to respond:** Service must listen on `0.0.0.0:$PORT` (this ZIP handles it); check the Railway deployment logs.
- **Booking disappeared after redeploy:** Your persistent volume was not mounted to `/data`, or its mount path changed. Do not delete the volume; restore from backup if available.
- **Login session lost when restarted:** Expected; sessions are in server memory and users should log in again. Consultation data stays in the volume.
- **Database unavailable after trial:** Check Railway account plan/volume retention before trial expiration; use the usage dashboard and download a backup of the SQLite file via an appropriate Railway volume/CLI workflow.
- **Shows local browser localhost:** Do not use `START_HERE.bat` in the cloud; Railway uses `Dockerfile` to start it. The .bat is only for Windows localhost.

## Security and limitations

This is a **classroom demonstration** only. All six accounts use known classroom passwords and can be accessed by anyone who knows those passwords once the URL is public; share the domain and credentials **only with your professor**. Keep the GitHub repo private. Do not upload actual student records or use this as an official university portal. HTTPS is handled by Railway and its deployed session cookie is `Secure; HttpOnly; SameSite=Strict`. The app uses in-memory sessions (logging in again after restart is normal), and the small built-in Python HTTP server is suitable for a low-traffic demo, not a security-audited production service.

**PDF NFR-002:** Hosting on Railway improves remote availability, but uptime of 99.9% per academic term is not a proven guarantee of this Free/Trial deployment. **NFR-001:** Server-Sent Events send changes quickly when online, but the five-second timing target still needs measured testing on real devices and networks.
