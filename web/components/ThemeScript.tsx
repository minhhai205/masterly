/**
 * Applies the stored theme before React hydrates, so the page never flashes
 * in the wrong theme. Must stay a Server Component: in React 19 a <script>
 * rendered by a Client Component is inert on the client.
 */
export default function ThemeScript() {
  const themeScript = `
    (function() {
      try {
        var stored = localStorage.getItem('masterly-theme');
        var theme = stored === 'dark' || stored === 'light'
          ? stored
          : (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        var html = document.documentElement;
        html.classList.remove('dark', 'theme-snow');
        html.classList.add(theme === 'dark' ? 'dark' : 'theme-snow');
        localStorage.setItem('masterly-theme', theme);
      } catch (e) {
        /* localStorage may be disabled */
      }
    })();
  `;
  return (
    <script
      dangerouslySetInnerHTML={{ __html: themeScript }}
      suppressHydrationWarning
    />
  );
}
