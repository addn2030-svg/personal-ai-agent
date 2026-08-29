window.PORTFOLIO_LINKS = {
  github: "https://github.com/addn2030-svg",
  linkedin: "",
  x: "",
  instagram: "",
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
