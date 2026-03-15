/**
 * Frontend Logger Utility
 * Provides consistent logging across the Next.js application
 */

export enum LogLevel {
    DEBUG = 0,
    INFO = 1,
    SUCCESS = 2,
    WARN = 3,
    ERROR = 4,
}

class Logger {
    private minLevel: LogLevel;
    private isDevelopment: boolean;

    constructor() {
        this.isDevelopment = process.env.NODE_ENV === 'development';
        // In production, only show WARN and ERROR
        this.minLevel = this.isDevelopment ? LogLevel.DEBUG : LogLevel.WARN;
    }

    private shouldLog(level: LogLevel): boolean {
        return level >= this.minLevel;
    }

    private formatMessage(level: string, message: string, ...args: any[]): void {
        const timestamp = new Date().toLocaleTimeString();
        const prefix = `[${timestamp}] [${level}]`;

        switch (level) {
            case 'DEBUG':
                console.log(`%c${prefix}`, 'color: #6B7280', message, ...args);
                break;
            case 'INFO':
                console.info(`%c${prefix}`, 'color: #3B82F6', message, ...args);
                break;
            case 'SUCCESS':
                console.log(`%c${prefix}`, 'color: #10B981; font-weight: bold', message, ...args);
                break;
            case 'WARN':
                console.warn(`%c${prefix}`, 'color: #F59E0B; font-weight: bold', message, ...args);
                break;
            case 'ERROR':
                console.error(`%c${prefix}`, 'color: #EF4444; font-weight: bold', message, ...args);
                break;
        }
    }

    debug(message: string, ...args: any[]): void {
        if (this.shouldLog(LogLevel.DEBUG)) {
            this.formatMessage('DEBUG', message, ...args);
        }
    }

    info(message: string, ...args: any[]): void {
        if (this.shouldLog(LogLevel.INFO)) {
            this.formatMessage('INFO', message, ...args);
        }
    }

    success(message: string, ...args: any[]): void {
        if (this.shouldLog(LogLevel.SUCCESS)) {
            this.formatMessage('SUCCESS', message, ...args);
        }
    }

    warn(message: string, ...args: any[]): void {
        if (this.shouldLog(LogLevel.WARN)) {
            this.formatMessage('WARN', message, ...args);
        }
    }

    error(message: string, error?: any): void {
        if (this.shouldLog(LogLevel.ERROR)) {
            this.formatMessage('ERROR', message);
            if (error) {
                console.error('Error details:', error);
                if (error?.stack) {
                    console.error('Stack trace:', error.stack);
                }
            }
        }
    }

    /**
     * Log API request
     */
    apiRequest(method: string, url: string, data?: any): void {
        this.debug(`API Request: ${method} ${url}`, data || '');
    }

    /**
     * Log API response
     */
    apiResponse(method: string, url: string, status: number, data?: any): void {
        if (status >= 200 && status < 300) {
            this.success(`API Response: ${method} ${url} - ${status}`, data || '');
        } else {
            this.error(`API Response: ${method} ${url} - ${status}`, data);
        }
    }

    /**
     * Log user action
     */
    userAction(action: string, details?: any): void {
        this.info(`User Action: ${action}`, details || '');
    }

    /**
     * Group logs together
     */
    group(label: string, collapsed: boolean = false): void {
        if (this.isDevelopment) {
            collapsed ? console.groupCollapsed(label) : console.group(label);
        }
    }

    groupEnd(): void {
        if (this.isDevelopment) {
            console.groupEnd();
        }
    }
}

// Export singleton instance
export const logger = new Logger();

// Export default for convenience
export default logger;
