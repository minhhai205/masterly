/** @type {import('next').NextConfig} */
const nextConfig = {
  // Do not generate AGENTS.md / CLAUDE.md into the project on `next dev`.
  agentRules: false,
};

module.exports = nextConfig;
