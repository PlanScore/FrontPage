const htmlblock = `
  <div class="footer">
    <div class="callout">
      <a href="https://campaignlegal.org" target="_blank" title="Visit Campaign Legal Center">
        <img src="/images/CLC-logo.svg" alt="Campaign Legal Center Logo" />
      </a>
      <p>
        PlanScore is a project of Campaign Legal Center.
      </p>
    </div>
    <div class="links">
      <a target="_blank" href="mailto:info@planscore.org" title="Email PlanScore">
        <img src="https://planscore.org/images/email-logo.svg" alt="email icon">
      </a>
      <a target="_blank" href="https://twitter.com/PlanScore" title="PlanScore on Twitter">
        <img src="https://planscore.org/images/twitter-logo.svg" alt="Twitter icon">
      </a>
      <a target="_blank" href="https://github.com/PlanScore/PlanScore" title="PlanScore on GitHub">
        <img src="https://planscore.org/images/github-logo.svg" alt="GitHub icon">
      </a>
      <div class="legal">
        PlanScore is a 501(c)(3) non-profit organization, EIN 83-1367310
      </div>
    </div>
  </div>

  <script async src="https://www.googletagmanager.com/gtag/js?id=UA-65629552-4"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());

    gtag('config', 'UA-65629552-4');
  </script>
  `;
module.exports = htmlblock;
