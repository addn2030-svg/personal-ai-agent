window.PORTFOLIO_LINKS = {
  github: "https://github.com/addn2030-svg",
  linkedin: "https://www.linkedin.com/in/abdulrahman-howsawy-89757825",
  x: "https://x.com/ABDUL4000",
  instagram: "https://www.instagram.com/ABDUL4000",
  tiktok: "https://www.tiktok.com/@add30nkt",
  facebook: "https://www.facebook.com/ABDUL4000",
  youtube: ""
};

(function () {
  const links = window.PORTFOLIO_LINKS || {};
  document.querySelectorAll("[data-social]").forEach((el) => {
    const key = el.getAttribute("data-social");
    const url = (links[key] || "").trim();
    if (!url) {
      el.hidden = true;
      return;
    }
    el.href = url;
    el.target = "_blank";
    el.rel = "noopener noreferrer";
  });
})();
