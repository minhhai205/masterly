"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus, register } from "@/lib/auth";

const AFTER_REGISTER_PATH = "/";

const INPUT_CLASS = `w-full px-3.5 py-2.5 rounded-lg border border-[var(--border)]
  bg-[var(--background)] text-[var(--foreground)]
  placeholder:text-[var(--muted-foreground)]
  focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent
  transition-shadow text-sm`;

const LABEL_CLASS = "block text-sm font-medium text-[var(--foreground)] mb-1.5";

export default function RegisterPage() {
  const { t } = useTranslation();
  const router = useRouter();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Already signed in: nothing to register.
    fetchAuthStatus().then((status) => {
      if (status?.authenticated) router.replace("/");
    });
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError(t("Use a password of at least 8 characters"));
      return;
    }
    if (password !== confirm) {
      setError(t("Passwords do not match"));
      return;
    }
    setLoading(true);
    const result = await register(email, password, displayName);
    if (result.ok) {
      router.replace(AFTER_REGISTER_PATH);
    } else {
      setError(t(result.error ?? "Registration failed"));
      setLoading(false);
    }
  }

  return (
    <div className="w-full max-w-sm">
      <div className="text-center mb-8">
        <h1 className="font-serif text-2xl font-semibold text-[var(--foreground)] tracking-tight">
          Masterly
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {t("Create an account to start your group")}
        </p>
      </div>

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-sm px-8 py-8">
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="display-name" className={LABEL_CLASS}>
              {t("Display name")}{" "}
              <span className="font-normal text-[var(--muted-foreground)]">
                ({t("optional")})
              </span>
            </label>
            <input
              id="display-name"
              type="text"
              autoComplete="name"
              maxLength={80}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className={INPUT_CLASS}
            />
          </div>

          <div>
            <label htmlFor="email" className={LABEL_CLASS}>
              {t("Email")}
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={INPUT_CLASS}
            />
          </div>

          <div>
            <label htmlFor="password" className={LABEL_CLASS}>
              {t("Password")}
            </label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={INPUT_CLASS}
              placeholder={t("At least 8 characters")}
            />
          </div>

          <div>
            <label htmlFor="confirm-password" className={LABEL_CLASS}>
              {t("Confirm password")}
            </label>
            <input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className={INPUT_CLASS}
            />
          </div>

          {error && (
            <p className="text-sm text-red-500 bg-red-500/10 rounded-lg px-3 py-2">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 px-4 rounded-lg font-medium text-sm
                       bg-[var(--primary)] text-[var(--primary-foreground)]
                       hover:opacity-90 active:opacity-80
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-opacity"
          >
            {loading ? t("Creating account…") : t("Create account")}
          </button>
        </form>
      </div>

      <p className="mt-6 text-center text-sm text-[var(--muted-foreground)]">
        {t("Already have an account?")}{" "}
        <Link href="/login" className="font-medium text-[var(--primary)] hover:underline">
          {t("Sign in")}
        </Link>
      </p>
    </div>
  );
}
