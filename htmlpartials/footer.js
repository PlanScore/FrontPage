const htmlblock = `
    <div class="footer">
    <div class="container">
    <div class="row">
        <p class="col-sm-3 col-xs-6">
            <a target="_blank" href="mailto:info@planscore.org"><img src="https://planscore.org/images/email-logo.svg"> info@planscore.org</a>
        </p>
        <p class="col-sm-3 col-xs-6">
            <a target="_blank" href="https://twitter.com/PlanScore"><img src="https://planscore.org/images/twitter-logo.svg"> @PlanScore</a>
        </p>
        <p class="col-sm-3 col-xs-6">
            <a target="_blank" href="https://github.com/PlanScore/PlanScore"><img src="https://planscore.org/images/github-logo.svg"> Github</a>
        </p>
        <form class="col-sm-3 col-xs-6" action="https://www.paypal.com/donate" method="post" target="_top">
            <input type="hidden" name="hosted_button_id" value="C9G45F294EKEG" />
            <input type="submit" name="submit" title="PayPal - The safer, easier way to pay online!" alt="Donate with PayPal button" class="btn btn-primary" value="Donate" style="margin: 0;">
            <img alt="" border="0" src="https://www.paypal.com/en_US/i/scr/pixel.gif" width="1" height="1" />
        </form>
    </div>
    <div class="row">
        <span class="col-sm-12">
            PlanScore is a 501(c)(3) non-profit organization, EIN 83-1367310
        </span>
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
