/**
 * Empty stand-in for the `server-only` package, used by Vitest only.
 *
 * The real package's default export THROWS on import — that is the whole
 * point of it: Next.js resolves `server-only` to a no-op under its
 * `react-server` condition (Server Components) and to the throwing
 * version everywhere else (Client Components), so an accidental client
 * import fails the build. Vitest is "everywhere else", so without this
 * alias `lib/api.ts` could not even be loaded by its own tests.
 *
 * Aliased in vitest.config.ts. Next's build never sees this file, so the
 * guard still works in the app.
 */
export {};
