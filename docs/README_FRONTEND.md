To deploy the frontend to GitHub Pages:
1. Create a new public repo on GitHub and push the frontend/ directory as the repo root or as `docs/`.
2. In Settings > Pages, select the branch `main` and folder `/ (root)` or `/docs` depending where you put files.
3. Ensure `index.html` is in the website root. Tailwind CDN is used so no build step required.

Before using, update `app.js` -> API_URL to point to your deployed Flask backend.
