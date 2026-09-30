import { createFileRoute } from "@tanstack/react-router";
import { AuthScreen } from "@/lib/ansme";
export const Route = createFileRoute("/auth")({ head: () => ({ meta: [{ title: "Welcome — ANSME" }, { name: "description", content: "Get brutally honest purchase advice." }, { property: "og:title", content: "Welcome — ANSME" }, { property: "og:description", content: "Get brutally honest purchase advice." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }), component: AuthScreen });
