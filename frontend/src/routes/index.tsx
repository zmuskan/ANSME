import { Navigate, createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "ANSME — Don't Buy Dumb Stuff" },
      { name: "description", content: "Get brutally honest purchase advice before you buy." },
      { property: "og:title", content: "ANSME — Don't Buy Dumb Stuff" },
      { property: "og:description", content: "Get brutally honest purchase advice before you buy." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Index,
});

function Index() {
  return <Navigate to="/auth" replace />;
}
