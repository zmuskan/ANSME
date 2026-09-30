<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

- ANSME routes use supplied portrait media as immutable full-screen artwork, with interaction layered only in reserved open regions.
- Shared ANSME state lives in a client-safe context with typed service-facing models so a future API can replace mock data cleanly.
- ANSME renders inside a centered 430px portrait stage so supplied 941×1672 artwork stays uncropped and aligned with overlays.
