import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, errorInfo) {
        console.error("Uncaught error:", error, errorInfo);
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center p-6 text-center">
                    <div className="bg-slate-900 border border-red-500/30 p-8 rounded-2xl max-w-md shadow-2xl">
                        <div className="bg-red-500/10 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-6">
                            <AlertTriangle className="w-8 h-8 text-red-500" />
                        </div>
                        <h1 className="text-2xl font-black text-white mb-2">Something went wrong</h1>
                        <p className="text-slate-400 mb-8 text-sm leading-relaxed">
                            The application encountered an unexpected error. This often happens due to temporary network issues or mobile browser caching.
                        </p>
                        <button
                            onClick={() => window.location.reload()}
                            className="w-full bg-red-600 hover:bg-red-500 text-white font-bold py-3 rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-red-900/20"
                        >
                            <RefreshCw className="w-5 h-5" />
                            Refresh Application
                        </button>
                        <button
                            onClick={() => this.setState({ hasError: false })}
                            className="mt-4 text-xs font-bold text-slate-500 hover:text-slate-300 uppercase tracking-widest transition-colors"
                        >
                            Try to continue
                        </button>
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}

export default ErrorBoundary;
