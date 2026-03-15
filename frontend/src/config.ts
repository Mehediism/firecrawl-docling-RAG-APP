/**
 * Frontend Configuration
 * Handles environment variables with defaults
 */

const NEXT_PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const API_BASE_URL = `${NEXT_PUBLIC_API_URL}/api`;

export const CONFIG = {
    API_BASE_URL,
    IS_PRODUCTION: process.env.NODE_ENV === "production",
};

export default CONFIG;
