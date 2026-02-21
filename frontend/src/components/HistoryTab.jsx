import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Loader2, Trash2, CheckCircle, XCircle, BrainCircuit } from 'lucide-react';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const HistoryTab = ({ onSelectHistoryItem }) => {
    const [history, setHistory] = useState([]);
    const [loading, setLoading] = useState(true);
    const [gradingIds, setGradingIds] = useState([]);

    useEffect(() => {
        fetchHistory();
    }, []);

    const fetchHistory = async () => {
        setLoading(true);
        try {
            const response = await axios.get(`${API_URL}/history`);
            setHistory(response.data);
        } catch (err) {
            console.error("Failed to fetch history:", err);
        } finally {
            setLoading(false);
        }
    };

    const handleClearHistory = async () => {
        if (window.confirm("Are you sure you want to delete all prediction history?")) {
            try {
                await axios.delete(`${API_URL}/history`);
                setHistory([]);
            } catch (err) {
                console.error("Failed to clear history:", err);
            }
        }
    };

    const handleGradePrediction = async (match_id) => {
        setGradingIds(prev => [...prev, match_id]);
        try {
            const response = await axios.post(`${API_URL}/grade-history`, { match_id });
            const gradedResult = response.data.graded_result;

            // Update local state to reflect the new grade instantly
            setHistory(prevHistory =>
                prevHistory.map(item =>
                    item.match_id === match_id
                        ? { ...item, actual_result: gradedResult.actual_score, is_correct: gradedResult.is_correct }
                        : item
                )
            );
        } catch (err) {
            console.error(err);
            alert("Failed to grade prediction. AI Agent may have timed out or hit search limits.");
        } finally {
            setGradingIds(prev => prev.filter(id => id !== match_id));
        }
    };

    if (loading) {
        return (
            <div className="flex justify-center items-center py-20">
                <Loader2 className="w-8 h-8 animate-spin text-purple-500" />
            </div>
        );
    }

    return (
        <div className="bg-gray-800 rounded-xl shadow-lg border border-gray-700 p-6 w-full mt-6">
            <div className="flex justify-between items-center mb-6">
                <div>
                    <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                        Prediction History
                    </h2>
                    <p className="text-sm text-gray-400 mt-1">Saved AI analyses from your database.</p>
                </div>

                {history.length > 0 && (
                    <button
                        onClick={handleClearHistory}
                        className="flex items-center gap-2 px-4 py-2 bg-red-500/10 text-red-400 border border-red-500/20 rounded-lg hover:bg-red-500/20 transition-colors"
                    >
                        <Trash2 className="w-4 h-4" /> Clear History
                    </button>
                )}
            </div>

            {history.length === 0 ? (
                <div className="text-center py-12 text-gray-500 bg-gray-900/50 rounded-lg border border-dashed border-gray-700">
                    No predictions saved yet. Run some analysis on the Calendar tab!
                </div>
            ) : (
                <div className="space-y-4">
                    {history.map((item) => {
                        const isGrading = gradingIds.includes(item.match_id);

                        return (
                            <div
                                key={item.id}
                                onClick={() => onSelectHistoryItem && onSelectHistoryItem(item)}
                                className="bg-gray-900 border border-gray-700 rounded-xl p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 hover:border-purple-500/50 hover:bg-gray-800/80 cursor-pointer transition-all shadow-sm hover:shadow-purple-900/10"
                            >

                                {/* Info Box */}
                                <div className="flex-1">
                                    <div className="text-xs text-gray-400 font-mono mb-1">{item.match_date}</div>
                                    <h3 className="text-lg font-bold text-white">{item.teams || "Unknown Match"}</h3>
                                    <div className="mt-2 inline-flex items-center px-3 py-1 rounded-full bg-slate-800 border border-slate-700">
                                        <span className="text-xs text-gray-400 mr-2">TIP:</span>
                                        <span className="text-sm font-semibold text-accent-green">{item.safe_bet_tip}</span>
                                        <span className="ml-2 px-2 py-0.5 rounded-full bg-black/50 text-[10px] text-gray-300 font-mono">
                                            {item.confidence}%
                                        </span>
                                    </div>
                                    {item.actual_result && (
                                        <div className="mt-2 text-sm text-gray-300">
                                            Result: <span className="font-mono bg-black/30 px-2 py-0.5 rounded">{item.actual_result}</span>
                                        </div>
                                    )}
                                </div>

                                {/* Status / Actions */}
                                <div className="flex items-center justify-end md:w-48 shrink-0">
                                    {item.is_correct === 1 || item.is_correct === true ? (
                                        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-500/10 text-green-400 border border-green-500/20 w-full justify-center">
                                            <CheckCircle className="w-5 h-5" />
                                            <span className="font-bold">WIN</span>
                                        </div>
                                    ) : item.is_correct === 0 || item.is_correct === false ? (
                                        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 text-red-500 border border-red-500/20 w-full justify-center">
                                            <XCircle className="w-5 h-5" />
                                            <span className="font-bold">LOSS</span>
                                        </div>
                                    ) : (
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                handleGradePrediction(item.match_id);
                                            }}
                                            disabled={isGrading}
                                            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-lg font-semibold shadow-lg shadow-blue-500/20 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                                        >
                                            {isGrading ? (
                                                <Loader2 className="w-5 h-5 animate-spin" />
                                            ) : (
                                                <>
                                                    <BrainCircuit className="w-4 h-4" /> Grade AI
                                                </>
                                            )}
                                        </button>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};

export default HistoryTab;
