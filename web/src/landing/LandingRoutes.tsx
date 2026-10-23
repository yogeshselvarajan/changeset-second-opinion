import { Seo } from "../seo/Seo";
import { Landing } from "./Landing";
import { pageFor } from "./pages";
import { About, Privacy } from "./TextPages";

function PageSeo({ path }: { path: "/" | "/about" | "/privacy" }) {
  const page = pageFor(path);
  return (
    <Seo
      title={page.title}
      description={page.description}
      canonicalPath={path}
      jsonLd={page.jsonLd}
    />
  );
}

export function HomePage() {
  return (
    <>
      <PageSeo path="/" />
      <Landing />
    </>
  );
}

export function AboutPage() {
  return (
    <>
      <PageSeo path="/about" />
      <About />
    </>
  );
}

export function PrivacyPage() {
  return (
    <>
      <PageSeo path="/privacy" />
      <Privacy />
    </>
  );
}
