const htmlblock = `
  <nav class="navbar navbar-default">
    <div class="container">
      <div class="navbar-header">
        <button type="button" class="navbar-toggle collapsed" data-toggle="collapse" data-target="#navbar" aria-expanded="false">
            <span class="sr-only">Toggle navigation</span>
            <span class="icon-bar"></span>
            <span class="icon-bar"></span>
            <span class="icon-bar"></span>
        </button>
        <a class="navbar-brand" href="/"><img id="brand-logo" src="/images/logo.svg" alt="PlanScore: a project of Campaign Legal Center"/></a>
    </div>
    <div class="collapse navbar-collapse" id="navbar">
        <ul class="nav navbar-nav navbar-right">
          <li class="mobile-only"><a href="/">Home</a></li>
          <li><a href="/upload.html">Score a Plan</a></li>
          <li><a href="/library">View 2022 Plans</a></li>
          <li><a href="/about/">What is PlanScore?</a></li>
        </ul>
      </div>
    </div>
  </nav>
`;
module.exports = htmlblock;
