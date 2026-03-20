import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Loader2, FolderOpen, ArrowLeft, Trash2, FolderMinus, Sparkles, Copy } from 'lucide-react';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
    baseURL: API_URL,
    timeout: 1800000 // 30 minutes
});

api.interceptors.request.use((config) => {
    const token = localStorage.getItem('token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

const GroupsTab = ({ onSelectHistoryItem }) => {
    const getLogoUrl = (logoPath) => {
        if (!logoPath) return null;
        if (logoPath.startsWith('http') || logoPath.startsWith(API_URL)) return logoPath;
        const path = logoPath.startsWith('/') ? logoPath : `/${logoPath}`;
        return `${API_URL}${path}`;
    };

    const [groups, setGroups] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selectedGroup, setSelectedGroup] = useState(null);
    const [groupMatches, setGroupMatches] = useState([]);
    const [loadingMatches, setLoadingMatches] = useState(false);
    const [isLoggedIn, setIsLoggedIn] = useState(!!localStorage.getItem('token'));

    useEffect(() => {
        fetchGroups();
    }, []);

    const fetchGroups = async () => {
        setLoading(true);
        try {
            const response = await api.get('/groups');
            setGroups(response.data);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const fetchGroupMatches = async (groupId) => {
        setLoadingMatches(true);
        try {
            const response = await api.get(`/groups/${groupId}/matches`);
            setGroupMatches(response.data);
        } catch (err) {
            console.error(err);
        } finally {
            setLoadingMatches(false);
        }
    };

    const handleSelectGroup = (group) => {
        setSelectedGroup(group);
        fetchGroupMatches(group.id);
    };

    const handleBackToGroups = () => {
        setSelectedGroup(null);
        setGroupMatches([]);
        fetchGroups(); // refresh counts
    };

    const handleRemoveFromGroup = async (e, id) => {
        e.stopPropagation();
        if (!selectedGroup) return;

        try {
            await api.delete(`/groups/${selectedGroup.id}/matches/${id}`);
            setGroupMatches(prev => prev.filter(m => m.id !== id));
        } catch (err) {
            alert("Failed to remove match from folder.");
        }
    };

    const handleDeleteGroup = async (e, groupId) => {
        e.stopPropagation();
        if (window.confirm("Are you sure you want to delete this folder entirely? This will not delete the predictions from the main History tab, only the folder itself.")) {
            try {
                await api.delete(`/groups/${groupId}`);
                setGroups(prev => prev.filter(g => g.id !== groupId));
            } catch (err) {
                alert("Failed to delete folder.");
            }
        }
    };

    const handleCopyToHistory = async (e, id) => {
        e.stopPropagation();
        try {
            await api.post(`/history/${id}/restore`);
            alert("Match successfully restored to History tab!");
        } catch (err) {
            alert("Failed to restore match to history.");
            console.error(err);
        }
    };

    if (loading) {
        return (
            <div className="flex justify-center items-center py-20">
                <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
            </div>
        );
    }

    if (selectedGroup) {
        return (
            <div className="bg-gray-800 rounded-xl shadow-lg border border-gray-700 p-6 w-full mt-6">
                <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 mb-6 pb-4 border-b border-gray-700">
                    <button
                        onClick={handleBackToGroups}
                        className="p-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-gray-300 hover:text-white transition-colors flex items-center gap-2 text-sm"
                    >
                        <ArrowLeft className="w-4 h-4" /> Back
                    </button>
                    <div>
                        <h2 className="text-xl md:text-2xl font-bold text-white flex items-center gap-2">
                            <FolderOpen className="text-blue-400" /> {selectedGroup.name}
                        </h2>
                        <p className="text-xs md:text-sm text-gray-400 mt-1">Viewing organized matches.</p>
                    </div>
                </div>

                {loadingMatches ? (
                    <div className="flex justify-center py-12">
                        <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
                    </div>
                ) : groupMatches.length === 0 ? (
                    <div className="text-center py-12 text-gray-500 bg-gray-900/50 rounded-lg border border-dashed border-gray-700">
                        This folder is empty. Admins can add matches from the History tab.
                    </div>
                ) : (
                    <div className="space-y-4">
                        {groupMatches.map((item) => (
                            <div
                                key={item.id}
                                onClick={() => onSelectHistoryItem && onSelectHistoryItem(item)}
                                className="bg-gray-900 border border-gray-700 rounded-xl p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 hover:border-blue-500/50 hover:bg-gray-800/80 cursor-pointer transition-all shadow-sm"
                            >
                                <div className="flex-1 w-full min-w-0">
                                    <div className="flex justify-between items-start mb-1">
                                        <div className="text-[10px] md:text-xs text-gray-400 font-mono">
                                            {(() => {
                                                try {
                                                    if (!item.match_date) return "Date Pending";
                                                    return new Date(item.match_date).toLocaleString('en-GB', {
                                                        timeZone: 'Africa/Lagos',
                                                        dateStyle: 'medium',
                                                        timeStyle: 'short'
                                                    });
                                                } catch (e) {
                                                    console.error("Date formatting error:", e);
                                                    return item.match_date || "Unknown Date";
                                                }
                                            })()}
                                        </div>
                                        <div className="flex gap-2">
                                            <button
                                                onClick={(e) => handleCopyToHistory(e, item.id)}
                                                className="flex items-center gap-1.5 px-2 py-1 text-[10px] text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 rounded-lg transition-colors border border-blue-500/20"
                                                title="Copy to Prediction History"
                                            >
                                                <Copy className="w-3 h-3" /> <span className="hidden xs:inline">Restore</span>
                                            </button>
                                            {isLoggedIn && (
                                                <button
                                                    onClick={(e) => handleRemoveFromGroup(e, item.id)}
                                                    className="p-1.5 text-gray-500 hover:text-orange-500 hover:bg-orange-500/10 rounded-lg transition-colors"
                                                    title="Remove from Folder"
                                                >
                                                    <FolderMinus className="w-4 h-4" />
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-3 mb-2 min-w-0">
                                        <div className="flex items-center gap-2 bg-gray-950/30 px-3 py-1.5 rounded-lg border border-gray-800/50 min-w-0">
                                            {item.home_logo && <img src={getLogoUrl(item.home_logo)} alt="H" className="w-8 h-8 shrink-0 object-contain rounded-full bg-white p-0.5 border border-gray-700" />}
                                            <span className="text-base font-bold text-white truncate">{item.teams?.includes(' vs ') ? item.teams.split(' vs ')[0] : "Home"}</span>
                                            <span className="text-gray-500 text-xs font-black px-1 shrink-0">VS</span>
                                            <span className="text-base font-bold text-white truncate">{item.teams?.includes(' vs ') ? item.teams.split(' vs ')[1] : "Away"}</span>
                                            {item.away_logo && <img src={getLogoUrl(item.away_logo)} alt="A" className="w-8 h-8 shrink-0 object-contain rounded-full bg-white p-0.5 border border-gray-700" />}
                                        </div>
                                    </div>
                                    <div className="flex flex-col gap-2">
                                        <div className="inline-flex items-center px-3 py-1 rounded-full bg-slate-800 border border-emerald-500/20 w-fit">
                                            <span className="text-[10px] md:text-xs text-emerald-400 mr-2 font-bold">SAFEST:</span>
                                            <span className="text-xs md:text-sm font-semibold text-emerald-300">{item.primary_pick?.tip || item.safe_bet_tip}</span>
                                            <span className="ml-2 px-2 py-0.5 rounded-full bg-black/50 text-[10px] text-emerald-200 font-mono">
                                                {item.primary_pick?.confidence || item.confidence}%
                                            </span>
                                        </div>
                                        {item.alternative_pick?.tip && (
                                            <div className="inline-flex items-center px-3 py-1 rounded-full bg-slate-800 border border-amber-500/20 w-fit">
                                                <span className="text-[10px] md:text-xs text-amber-500 mr-2 font-bold">VALUE:</span>
                                                <span className="text-xs md:text-sm font-semibold text-amber-400">{item.alternative_pick.tip}</span>
                                                <span className="ml-2 px-2 py-0.5 rounded-full bg-black/50 text-[10px] text-amber-200 font-mono">
                                                    {item.alternative_pick.confidence ?? 'N/A'}%
                                                </span>
                                            </div>
                                        )}
                                    </div>
                                    {item.actual_result && (
                                        <div className="mt-2 text-[10px] md:text-xs text-gray-300">
                                            Result: <span className="font-mono bg-black/30 px-2 py-0.5 rounded text-white">{item.actual_result}</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        );
    }

    return (
        <div className="bg-gray-800 rounded-xl shadow-lg border border-gray-700 p-6 w-full mt-6">
            <div className="mb-8">
                <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                    <FolderOpen className="text-blue-400" /> Prediction Folders
                </h2>
                <p className="text-sm text-gray-400 mt-1">Organized collections of matches. Create these from the main History tab.</p>
            </div>

            {groups.length === 0 ? (
                <div className="text-center py-16 text-gray-500 bg-gray-900/50 rounded-lg border border-dashed border-gray-700 flex flex-col items-center">
                    <Sparkles className="w-12 h-12 text-gray-600 mb-3" />
                    <p>No folders created yet.</p>
                    <p className="text-sm mt-1">Admins can click the Folder icon on any match in the History Tab to create a new group.</p>
                </div>
            ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
                    {groups.map(g => (
                        <div
                            key={g.id}
                            onClick={() => handleSelectGroup(g)}
                            className="bg-gray-900 border border-gray-700 rounded-xl p-6 hover:border-blue-500/50 cursor-pointer transition-all shadow-sm hover:shadow-blue-900/10 group relative flex flex-col"
                        >
                            {isLoggedIn && (
                                <button
                                    onClick={(e) => handleDeleteGroup(e, g.id)}
                                    className="absolute top-4 right-4 p-2 text-gray-600 hover:text-red-500 hover:bg-red-500/10 rounded-lg opacity-0 group-hover:opacity-100 transition-all z-10"
                                    title="Delete Folder"
                                >
                                    <Trash2 className="w-5 h-5" />
                                </button>
                            )}
                            <FolderOpen className="w-12 h-12 text-gradient-to-br from-blue-400 to-blue-600 text-blue-500 mb-4 opacity-80 group-hover:scale-110 transition-transform" />
                            <h3 className="text-xl font-bold text-white mb-2 truncate pr-6">{g.name}</h3>
                            <div className="mt-auto pt-4 border-t border-gray-800 flex items-center justify-between text-xs text-gray-400">
                                <span className="bg-gray-800/80 px-2.5 py-1 rounded-full font-medium border border-gray-700 shadow-inner">
                                    {g.match_count} matches
                                </span>
                                <span>{g.created_at ? new Date(g.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' }) : 'N/A'}</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default GroupsTab;
