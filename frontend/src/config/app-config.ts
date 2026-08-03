import packageJson from "../../package.json";

const currentYear = new Date().getFullYear();

export const APP_CONFIG = {
  name: "ATLAS",
  version: packageJson.version,
  copyright: `© ${currentYear}, ATLAS Trading Platform.`,
  meta: {
    title: "ATLAS — Trading Platform Console",
    description:
      "ATLAS admin console — terminals, trading, strategies, risk, AI, and analytics for the ATLAS algorithmic trading platform.",
  },
};
