# Expert Portfolio

This folder contains the public-facing professional portfolio for Abdulrahman Bakr Hawsawi.

## Included work
- Advanced rehabilitation and movement/pain analysis
- Fascial Functional Assessment
- MyoMentor AI
- Personal Business Manager (in development)
- IMTAF / Precision Rehabilitation
- Rehabilitation operations and responsible healthcare AI

## Social links
Edit only `links.js` and add the exact public profile URL for each platform:

```js
window.PORTFOLIO_LINKS = {
  github: "https://github.com/addn2030-svg",
  linkedin: "https://www.linkedin.com/in/YOUR-PROFILE",
  x: "https://x.com/YOUR-HANDLE",
  instagram: "https://instagram.com/YOUR-HANDLE",
  youtube: "https://youtube.com/@YOUR-HANDLE"
};
```

Empty links remain hidden automatically.

## Publishing
The repository includes `.github/workflows/portfolio-pages.yml`, which uploads only the `portfolio/` directory to GitHub Pages. This prevents the private agent code, data, and internal documentation from being included in the Pages artifact.

If GitHub Pages is not yet enabled for this repository, enable GitHub Pages with **GitHub Actions** as the source in repository Settings → Pages. The deployment workflow will then publish this folder.

## Privacy
Do not add patient-identifiable information, credentials, API keys, private calendar data, internal hospital documents, or confidential business records to this public portfolio.
