const htmlblock = `
  <div class="container">
    <nav class="navbar navbar-light navbar-expand-md">
      <a class="navbar-brand" href="/"><img id="brand-logo" src="/images/logo.svg" alt="PlanScore: a project of Campaign Legal Center"/></a>
      <button type="button" class="navbar-toggler collapsed" data-toggle="collapse" data-target="#navbar" aria-expanded="false">
          <span class="sr-only">Toggle navigation</span>
          <span class="navbar-toggler-icon"></span>
      </button>
      <div class="collapse navbar-collapse d-flex justify-content-end" id="navbar">
        <ul class="nav navbar-nav navbar-right">
          <li class="nav-item mobile-only"><a class="nav-link" href="/">Home</a></li>
          <li class="nav-item"><a class="nav-link" href="/upload.html">Score a Plan</a></li>
          <li class="nav-item"><a class="nav-link" href="/about/">What is PlanScore?</a></li>
        </ul>
      </div>
    </nav>
  </div>
`;
module.exports = htmlblock;
