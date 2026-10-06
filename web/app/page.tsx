"use client";

import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";

type Health = { status: string; version: string };

export default function HomePage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(apiUrl("/api/health"))
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then(setHealth)
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-4 p-6">
      <h1 className="text-3xl font-semibold">Masterly</h1>
      <p className="text-gray-600">Không gian học tập AI cá nhân hóa.</p>
      <p className="text-sm">
        Backend:{" "}
        {health ? (
          <span className="text-green-700">OK (v{health.version})</span>
        ) : error ? (
          <span className="text-red-700">lỗi kết nối ({error})</span>
        ) : (
          <span className="text-gray-500">đang kiểm tra…</span>
        )}
      </p>
    </main>
  );
}
