import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.5/firebase-app.js";
import {
  getAnalytics,
  isSupported,
} from "https://www.gstatic.com/firebasejs/10.12.5/firebase-analytics.js";

const firebaseConfig = {
  apiKey: "AIzaSyDxXzvsMu3uAgGOT909wqsU50dI6Zxi61E",
  authDomain: "dutymaker-8e6a9.firebaseapp.com",
  projectId: "dutymaker-8e6a9",
  storageBucket: "dutymaker-8e6a9.firebasestorage.app",
  messagingSenderId: "1055216889529",
  appId: "1:1055216889529:web:5f586bd2e472a507b43568",
  measurementId: "G-S4TMFTFDRK",
};

export const firebaseApp = initializeApp(firebaseConfig);

export async function initializeFirebaseAnalytics() {
  if (!(await isSupported())) return null;
  return getAnalytics(firebaseApp);
}
