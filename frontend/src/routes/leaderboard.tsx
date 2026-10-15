import { createFileRoute } from "@tanstack/react-router";
import { LeaderboardScreen } from "@/lib/ansme";

export const Route = createFileRoute("/leaderboard")({
  head: () => ({
    meta: [
      { title: "Leaderboard — ANSME" },
      { name: "description", content: "Explore the highest and lowest scored analyzed products." },
    ],
  }),
  component: LeaderboardScreen,
});
