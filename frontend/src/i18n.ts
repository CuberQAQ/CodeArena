import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

// English
import enCommon from "./locales/en/common.json";
import enNav from "./locales/en/nav.json";
import enAuth from "./locales/en/auth.json";
import enDashboard from "./locales/en/dashboard.json";
import enChallenge from "./locales/en/challenge.json";
import enTraining from "./locales/en/training.json";
import enContest from "./locales/en/contest.json";
import enProfile from "./locales/en/profile.json";
import enLeaderboard from "./locales/en/leaderboard.json";
import enAdmin from "./locales/en/admin.json";
import enRating from "./locales/en/rating.json";
import enFreePlay from "./locales/en/free_play.json";

// Chinese
import zhCommon from "./locales/zh/common.json";
import zhNav from "./locales/zh/nav.json";
import zhAuth from "./locales/zh/auth.json";
import zhDashboard from "./locales/zh/dashboard.json";
import zhChallenge from "./locales/zh/challenge.json";
import zhTraining from "./locales/zh/training.json";
import zhContest from "./locales/zh/contest.json";
import zhProfile from "./locales/zh/profile.json";
import zhLeaderboard from "./locales/zh/leaderboard.json";
import zhAdmin from "./locales/zh/admin.json";
import zhRating from "./locales/zh/rating.json";
import zhFreePlay from "./locales/zh/free_play.json";

const resources = {
  en: {
    common: enCommon,
    nav: enNav,
    auth: enAuth,
    dashboard: enDashboard,
    challenge: enChallenge,
    training: enTraining,
    contest: enContest,
    profile: enProfile,
    leaderboard: enLeaderboard,
    admin: enAdmin,
    rating: enRating,
    free_play: enFreePlay,
  },
  zh: {
    common: zhCommon,
    nav: zhNav,
    auth: zhAuth,
    dashboard: zhDashboard,
    challenge: zhChallenge,
    training: zhTraining,
    contest: zhContest,
    profile: zhProfile,
    leaderboard: zhLeaderboard,
    admin: zhAdmin,
    rating: zhRating,
    free_play: zhFreePlay,
  },
};

const namespaces = [
  "common",
  "nav",
  "auth",
  "dashboard",
  "challenge",
  "training",
  "contest",
  "profile",
  "leaderboard",
  "admin",
  "rating",
  "free_play",
];

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: "en",
    ns: namespaces,
    defaultNS: "common",
    resources,
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "i18nextLng",
    },
    interpolation: {
      escapeValue: false,
    },
  });

export default i18n;
