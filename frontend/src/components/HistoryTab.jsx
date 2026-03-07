import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Loader2, Trash2, CheckCircle, XCircle, BrainCircuit, Zap, FolderPlus } from 'lucide-react';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
    baseURL: API_URL,
    timeout: 1800000 // 30 minutes
});

// Axios Request Interceptor to inject JWT token
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

const HistoryTab = ({ onSelectHistoryItem }) => {
    const getLogoUrl = (logoPath) => {
        if (!logoPath) return null;
        if (logoPath.startsWith('http')) return logoPath;
        return `${API_URL}${logoPath}`;
    };

    const [history, setHistory] = useState([]);
    const [loading, setLoading] = useState(true);
    const [gradingIds, setGradingIds] = useState([]);

    // AI Accumulator State
    const [bestPicks, setBestPicks] = useState(null);
    const [generatingPicks, setGeneratingPicks] = useState(false);
    const [targetOdds, setTargetOdds] = useState('');

    // Groups State
    const [groups, setGroups] = useState([]);
    const [showGroupModal, setShowGroupModal] = useState(false);
    const [selectedMatchForGroup, setSelectedMatchForGroup] = useState(null);
    const [newGroupName, setNewGroupName] = useState('');
    const [isLoggedIn, setIsLoggedIn] = useState(!!localStorage.getItem('token'));

    useEffect(() => {
        fetchHistory();
        fetchBestPicks();
        fetchGroups();
    }, []);

    const fetchHistory = async () => {
        setLoading(true);
        try {
            const response = await api.get(`/history`);
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
                await api.delete(`/history`);
                setHistory([]);
            } catch (err) {
                console.error("Failed to clear history:", err);
            }
        }
    };

    const fetchBestPicks = async () => {
        try {
            const response = await api.get(`/best-picks`);
            if (response.data && response.data.picks) {
                setBestPicks(response.data);
            } else {
                setBestPicks(null);
            }
        } catch (err) {
            console.error("Failed to fetch best picks:", err);
        }
    };

    const handleGenerateBestPicks = async () => {
        setGeneratingPicks(true);
        try {
            const payload = targetOdds ? { target_odds: parseFloat(targetOdds) } : {};
            const response = await api.post(`/generate-best-picks`, payload);
            setBestPicks(response.data);
            setTargetOdds(''); // Reset after successful generation
        } catch (err) {
            console.error(err);
            alert("Failed to generate best picks. Make sure you have history saved!");
        } finally {
            setGeneratingPicks(false);
        }
    };

    const fetchGroups = async () => {
        try {
            const response = await api.get('/groups');
            setGroups(response.data);
        } catch (err) {
            console.error("Failed to fetch groups:", err);
        }
    };

    const handleAddToExistingGroup = async (groupId) => {
        try {
            await api.post(`/groups/${groupId}/matches`, { match_id: selectedMatchForGroup.match_id });
            alert("Match successfully added to group!");
            setShowGroupModal(false);
            fetchGroups(); // refresh counts
        } catch (err) {
            console.error(err);
            alert("Failed to add match to group.");
        }
    };

    const handleCreateGroupAndAdd = async () => {
        try {
            const res = await api.post('/groups', { name: newGroupName });
            const newGroupId = res.data.id;
            await api.post(`/groups/${newGroupId}/matches`, { match_id: selectedMatchForGroup.match_id });
            alert("Group created and match added!");
            setNewGroupName('');
            setShowGroupModal(false);
            fetchGroups();
        } catch (err) {
            alert(err.response?.data?.detail || "Failed to create group.");
        }
    };

    const handleClearBestPicks = async () => {
        if (window.confirm("Are you sure you want to delete the AI Accumulator?")) {
            try {
                await api.delete(`/best-picks`);
                setBestPicks(null);
            } catch (err) {
                console.error("Failed to clear best picks:", err);
            }
        }
    };

    const handleGradePrediction = async (match_id) => {
        setGradingIds(prev => [...prev, match_id]);
        try {
            const response = await api.post(`/grade-history`, { match_id });
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

    const handleDeletePrediction = async (e, match_id) => {
        // Prevent clicking the card behind the button
        e.stopPropagation();

        try {
            await api.delete(`/history/${match_id}`);
            // Filter out the deleted match from React state instantly
            setHistory(prevHistory => prevHistory.filter(item => item.match_id !== match_id));
        } catch (err) {
            console.error("Failed to delete prediction:", err);
            alert("Failed to delete prediction from database.");
        }
    };

    const maxSafeStats = React.useMemo(() => {
        if (!history || history.length === 0) return { odds: 0, count: 0 };
        // We only want to multiply odds for matches that haven't explicitly lost
        const eligible = history.filter(item => item.is_correct !== 0 && item.is_correct !== false);
        let total = 1.0;
        let count = 0;
        eligible.forEach(item => {
            const pickOdds = item.primary_pick?.odds;
            if (pickOdds && !isNaN(parseFloat(pickOdds))) {
                total *= parseFloat(pickOdds);
                count++;
            }
        });
        return { odds: count > 0 ? parseFloat(total.toFixed(2)) : 0, count };
    }, [history]);

    if (loading) {
        return (
            <div className="flex justify-center items-center py-20">
                <Loader2 className="w-8 h-8 animate-spin text-purple-500" />
            </div>
        );
    }

    return (
        <div className="bg-gray-800 rounded-xl shadow-lg border border-gray-700 p-6 w-full mt-6">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
                <div>
                    <h2 className="text-xl md:text-2xl font-bold text-white flex items-center gap-2">
                        Prediction History
                    </h2>
                    <p className="text-xs md:text-sm text-gray-400 mt-1">Saved AI analyses from your database.</p>
                </div>

                <div className="flex flex-col items-stretch sm:items-end gap-3 w-full sm:w-auto">
                    <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
                        <div className="relative w-full sm:w-48">
                            <input
                                type="number"
                                step="0.1"
                                min="1.1"
                                placeholder="Target Odds (e.g. 10.0)"
                                value={targetOdds}
                                onChange={(e) => setTargetOdds(e.target.value)}
                                disabled={generatingPicks || history.length === 0}
                                className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-amber-500 placeholder-gray-500 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                            />
                        </div>
                        <button
                            onClick={handleGenerateBestPicks}
                            disabled={generatingPicks || history.length === 0}
                            className="flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-white rounded-lg font-bold shadow-lg shadow-amber-500/20 disabled:opacity-50 disabled:cursor-not-allowed transition-all text-sm"
                        >
                            {generatingPicks ? (
                                <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                                <Zap className="w-4 h-4 fill-current" />
                            )}
                            {generatingPicks ? 'Analyzing...' : 'Build Accumulator'}
                        </button>

                        {history.length > 0 && (
                            <button
                                onClick={handleClearHistory}
                                className="flex items-center justify-center gap-2 px-4 py-2 bg-red-500/10 text-red-400 border border-red-500/20 rounded-lg hover:bg-red-500/20 transition-colors text-sm"
                            >
                                <Trash2 className="w-4 h-4" /> Clear
                            </button>
                        )}
                    </div>
                    {maxSafeStats.count > 0 && (
                        <div className="text-[10px] md:text-[11px] font-mono text-emerald-400/80 uppercase tracking-widest text-center sm:text-right">
                            Odd Limit: <strong className="text-emerald-300">{maxSafeStats.odds}x</strong> from {maxSafeStats.count} safe games
                        </div>
                    )}
                </div>
            </div>

            {/* AI Accumulator Section */}
            {bestPicks && bestPicks.picks && (
                <div className="mb-8 p-6 bg-gradient-to-br from-amber-500/10 to-orange-600/10 border border-amber-500/30 rounded-2xl relative overflow-hidden">
                    {/* Decorative Background Icon */}
                    <Zap className="absolute -right-10 -bottom-10 w-64 h-64 text-amber-500/5 rotate-12 pointer-events-none" />

                    <div className="flex justify-between items-start mb-4 relative z-10">
                        <div>
                            <div className="flex items-center gap-2 mb-2">
                                <Zap className="w-6 h-6 text-amber-500 fill-amber-500" />
                                <h3 className="text-xl font-black text-transparent bg-clip-text bg-gradient-to-r from-amber-300 to-orange-400">
                                    AI Master Accumulator
                                </h3>
                            </div>

                            {bestPicks.total_accumulator_odds && (
                                <div className="mb-3 inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-emerald-500/20 border border-emerald-500/30">
                                    <span className="text-sm font-bold text-emerald-400">Total Parlay Odds:</span>
                                    <span className="text-lg font-black text-white">{bestPicks.total_accumulator_odds}x</span>
                                </div>
                            )}
                            <p className="text-amber-100/80 text-sm max-w-3xl leading-relaxed">
                                {bestPicks.master_reasoning}
                            </p>
                        </div>
                        <button
                            onClick={handleClearBestPicks}
                            className="p-2 text-amber-500/50 hover:text-amber-400 hover:bg-amber-500/10 rounded-lg transition-colors"
                            title="Clear Best Picks"
                        >
                            <XCircle className="w-5 h-5" />
                        </button>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-6 relative z-10">
                        {bestPicks.picks.map((pick, idx) => (
                            <div key={idx} className="bg-gray-900/80 backdrop-blur-md border border-amber-500/20 rounded-xl p-4 flex gap-4 hover:border-amber-500/40 transition-colors">
                                <div className="flex-1">
                                    <div className="flex justify-between items-start mb-2">
                                        <div className="text-xs text-amber-500/70 font-mono">
                                            {new Date(pick.match_date).toLocaleString('en-GB', { timeZone: 'Africa/Lagos', dateStyle: 'short', timeStyle: 'short' })}
                                        </div>
                                    </div>
                                    <div className="flex justify-between items-center mb-3 bg-gray-950/50 p-2 rounded-lg border border-gray-800/50">
                                        <div className="flex items-center gap-2">
                                            {pick.home_logo && <img src={getLogoUrl(pick.home_logo)} alt="Home" className="w-8 h-8 object-contain rounded-full bg-white p-0.5 border border-gray-700" />}
                                            <span className="font-bold text-gray-200 text-sm">{pick.teams.split(' vs ')[0]}</span>
                                        </div>
                                        <span className="text-gray-600 text-[10px] font-bold">VS</span>
                                        <div className="flex items-center gap-2">
                                            <span className="font-bold text-gray-200 text-sm">{pick.teams.split(' vs ')[1]}</span>
                                            {pick.away_logo && <img src={getLogoUrl(pick.away_logo)} alt="Away" className="w-8 h-8 object-contain rounded-full bg-white p-0.5 border border-gray-700" />}
                                        </div>
                                    </div>

                                    <div className="inline-flex items-center px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 mb-3 flex-wrap gap-2">
                                        <div className="flex items-center">
                                            <span className="text-xs text-amber-500 mr-2 font-bold">SAFEST TIP:</span>
                                            <span className="text-sm font-black text-amber-400">{pick.chosen_tip || pick.safe_bet_tip}</span>
                                        </div>
                                        {pick.odds && (
                                            <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-[10px] text-emerald-300 font-mono font-bold border border-emerald-500/30">
                                                {pick.odds}
                                            </span>
                                        )}
                                        <span className="px-2 py-0.5 rounded-full bg-black/50 text-[10px] text-amber-300 font-mono">
                                            {pick.confidence}%
                                        </span>
                                    </div>

                                    <ul className="space-y-1">
                                        {pick.reasoning && pick.reasoning.map((r, i) => (
                                            <li key={i} className="text-xs text-gray-400 flex gap-2">
                                                <span className="text-amber-500 mt-0.5">•</span>
                                                {r}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

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
                                    <div className="flex justify-between items-start mb-1">
                                        <div className="text-xs text-gray-400 font-mono">
                                            {new Date(item.match_date).toLocaleString('en-GB', { timeZone: 'Africa/Lagos', dateStyle: 'medium', timeStyle: 'short' })}
                                        </div>
                                        <div className="flex gap-2">
                                            {isLoggedIn && (
                                                <button
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setSelectedMatchForGroup(item);
                                                        setShowGroupModal(true);
                                                    }}
                                                    className="p-1.5 text-gray-500 hover:text-blue-400 hover:bg-blue-500/10 rounded-lg transition-colors"
                                                    title="Add to Group Folder"
                                                >
                                                    <FolderPlus className="w-4 h-4" />
                                                </button>
                                            )}
                                            <button
                                                onClick={(e) => handleDeletePrediction(e, item.match_id)}
                                                className="p-1.5 text-gray-500 hover:text-red-500 hover:bg-red-500/10 rounded-lg transition-colors"
                                                title="Delete Prediction"
                                            >
                                                <Trash2 className="w-4 h-4" />
                                            </button>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-3 mb-2">
                                        <div className="flex items-center gap-2 bg-gray-950/30 px-3 py-1.5 rounded-lg border border-gray-800/50">
                                            {item.home_logo && <img src={getLogoUrl(item.home_logo)} alt="H" className="w-8 h-8 object-contain rounded-full bg-white p-0.5 border border-gray-700" />}
                                            <span className="text-base font-bold text-white">{item.teams ? item.teams.split(' vs ')[0] : "Home"}</span>
                                            <span className="text-gray-500 text-xs font-black px-1">VS</span>
                                            <span className="text-base font-bold text-white">{item.teams ? item.teams.split(' vs ')[1] : "Away"}</span>
                                            {item.away_logo && <img src={getLogoUrl(item.away_logo)} alt="A" className="w-8 h-8 object-contain rounded-full bg-white p-0.5 border border-gray-700" />}
                                        </div>
                                    </div>
                                    <div className="flex flex-col gap-2 mt-2">
                                        <div className="inline-flex items-center px-3 py-1 rounded-full bg-slate-800 border border-emerald-500/20 w-fit">
                                            <span className="text-xs text-emerald-400 mr-2 font-bold">SAFEST TIP:</span>
                                            <span className="text-sm font-semibold text-emerald-300">{item.primary_pick?.tip || item.safe_bet_tip}</span>
                                            <span className="ml-2 px-2 py-0.5 rounded-full bg-black/50 text-[10px] text-emerald-200 font-mono">
                                                {item.primary_pick?.confidence || item.confidence}%
                                            </span>
                                        </div>
                                        {item.alternative_pick && (
                                            <div className="inline-flex items-center px-3 py-1 rounded-full bg-slate-800 border border-amber-500/20 w-fit">
                                                <span className="text-xs text-amber-500 mr-2 font-bold">VALUE BET:</span>
                                                <span className="text-sm font-semibold text-amber-400">{item.alternative_pick.tip}</span>
                                                <span className="ml-2 px-2 py-0.5 rounded-full bg-black/50 text-[10px] text-amber-200 font-mono">
                                                    {item.alternative_pick.confidence}%
                                                </span>
                                            </div>
                                        )}
                                    </div>
                                    {item.actual_result && (
                                        <div className="mt-2 text-sm text-gray-300">
                                            Result: <span className="font-mono bg-black/30 px-2 py-0.5 rounded">{item.actual_result}</span>
                                        </div>
                                    )}
                                </div>

                                {/* Status / Actions */}
                                <div className="flex items-center justify-end w-full md:w-48 shrink-0">
                                    {item.is_correct === 1 || item.is_correct === true ? (
                                        <div className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-green-500/10 text-green-400 border border-green-500/20 w-full justify-center">
                                            <CheckCircle className="w-5 h-5" />
                                            <span className="font-bold">WIN</span>
                                        </div>
                                    ) : item.is_correct === 0 || item.is_correct === false ? (
                                        <div className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-red-500/10 text-red-500 border border-red-500/20 w-full justify-center">
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
                                            className="w-full flex items-center justify-center gap-2 px-4 py-3 md:py-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-lg font-bold shadow-lg shadow-blue-500/20 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
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

            {/* Group Assignment Modal */}
            {showGroupModal && selectedMatchForGroup && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                    <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 w-full max-w-sm shadow-2xl relative">
                        <button onClick={() => setShowGroupModal(false)} className="absolute top-4 right-4 text-gray-400 hover:text-white">×</button>
                        <h3 className="text-xl font-bold text-white flex items-center gap-2 mb-4">
                            <FolderPlus className="text-blue-400" /> Add to Group
                        </h3>

                        <div className="mb-4 bg-gray-900/50 p-3 rounded border border-gray-700">
                            <span className="text-xs text-gray-400 uppercase tracking-wider block mb-1">Target Match</span>
                            <p className="font-semibold text-sm text-gray-200">{selectedMatchForGroup.teams}</p>
                        </div>

                        {groups.length > 0 && (
                            <div className="mb-5 space-y-2 max-h-40 overflow-y-auto custom-scrollbar">
                                <label className="block text-sm font-medium text-gray-400 mb-1">Existing Folders</label>
                                {groups.map(g => (
                                    <button
                                        key={g.id}
                                        onClick={() => handleAddToExistingGroup(g.id)}
                                        className="w-full text-left px-3 py-3 bg-gray-700 hover:bg-gray-600 rounded flex justify-between items-center transition-colors border border-gray-600 hover:border-blue-500/50"
                                    >
                                        <span className="font-medium">{g.name}</span>
                                        <span className="text-xs text-gray-400 bg-gray-900/50 px-2 py-1 rounded">{g.match_count} matches</span>
                                    </button>
                                ))}
                            </div>
                        )}

                        <div className="mt-4 pt-5 border-t border-gray-700">
                            <label className="block text-sm font-medium text-gray-400 mb-2">Create New Folder</label>
                            <div className="flex gap-2">
                                <input
                                    type="text"
                                    value={newGroupName}
                                    onChange={e => setNewGroupName(e.target.value)}
                                    placeholder="e.g. Monday's Matches"
                                    className="flex-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500 text-sm"
                                />
                                <button
                                    onClick={handleCreateGroupAndAdd}
                                    disabled={!newGroupName.trim()}
                                    className="px-4 py-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 rounded text-white font-semibold flex items-center gap-2 shadow-lg disabled:opacity-50 transition-colors text-sm"
                                >
                                    Create
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default HistoryTab;
