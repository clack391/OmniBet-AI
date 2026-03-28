import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Loader2, Database, ShieldAlert, Save } from 'lucide-react';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
    baseURL: API_URL,
});

api.interceptors.request.use((config) => {
    const token = localStorage.getItem('token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

const SettingsTab = () => {
    const [provider, setProvider] = useState('football-data');
    const [geminiModel, setGeminiModel] = useState('gemini-3-pro-preview');
    const [automationEnabled, setAutomationEnabled] = useState(true);
    const [telegramMode, setTelegramMode] = useState('text');
    const [killSignalActive, setKillSignalActive] = useState(false);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState(null);

    useEffect(() => {
        const fetchSettings = async () => {
            try {
                const providerRes = await api.get('/settings/provider');
                setProvider(providerRes.data.provider);

                const automationRes = await api.get('/settings/automation');
                setAutomationEnabled(automationRes.data.enabled);

                const telegramRes = await api.get('/settings/telegram-mode');
                setTelegramMode(telegramRes.data.mode);

                const modelRes = await api.get('/settings/gemini-model');
                setGeminiModel(modelRes.data.model);

                const killRes = await api.get('/settings/kill-active-cron');
                setKillSignalActive(killRes.data.active);
            } catch (err) {
                console.error("Failed to fetch settings", err);
            } finally {
                setLoading(false);
            }
        };
        fetchSettings();
    }, []);

    const handleSave = async () => {
        setSaving(true);
        setMessage(null);
        try {
            await Promise.all([
                api.put('/settings/provider', { provider }),
                api.put('/settings/gemini-model', { model: geminiModel }),
                api.put('/settings/automation', { enabled: automationEnabled }),
                api.put('/settings/telegram-mode', { mode: telegramMode })
            ]);
            setMessage({ type: 'success', text: 'Settings updated successfully!' });
        } catch (err) {
            setMessage({ type: 'error', text: 'Failed to update settings.' });
            console.error(err);
        } finally {
            setSaving(false);
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
        <div className="max-w-4xl mx-auto space-y-6 animate-fade-in pb-12">
            <div className="bg-gray-800 rounded-xl p-4 md:p-6 shadow-lg border border-gray-700">
                <div className="flex items-center gap-3 mb-6 border-b border-gray-700 pb-4">
                    <Database className="w-6 h-6 text-teal-400" />
                    <div>
                        <h2 className="text-xl font-bold text-white">System Settings</h2>
                        <p className="text-sm text-gray-400">Manage the core API sources and automated background tasks</p>
                    </div>
                </div>

                {message && (
                    <div className={`p-4 rounded-md mb-6 ${message.type === 'success' ? 'bg-green-900/30 border border-green-500/50 text-green-300' : 'bg-red-900/30 border border-red-500/50 text-red-300'}`}>
                        {message.text}
                    </div>
                )}

                <div className="space-y-6">
                    {/* Data Provider Section */}
                    <div className="bg-gray-900/50 p-5 rounded-lg border border-gray-700">
                        <h3 className="text-lg font-semibold text-gray-200 mb-4">Primary Match Data Source</h3>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {/* Option 1: Football Data */}
                            <label className={`cursor-pointer border rounded-xl p-4 transition-all ${provider === 'football-data' ? 'bg-purple-900/30 border-purple-500 shadow-[0_0_15px_rgba(168,85,247,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}>
                                <div className="flex items-start gap-4">
                                    <div className="pt-1">
                                        <input
                                            type="radio"
                                            name="provider"
                                            value="football-data"
                                            checked={provider === 'football-data'}
                                            onChange={(e) => setProvider(e.target.value)}
                                            className="w-4 h-4 text-purple-600 bg-gray-700 border-gray-600 focus:ring-purple-500 focus:ring-2"
                                        />
                                    </div>
                                    <div>
                                        <div className="font-bold text-white text-lg">football-data.org</div>
                                        <div className="text-xs text-green-400 font-medium mb-2 opacity-80 mt-1 uppercase tracking-wider">Default • Stable</div>
                                        <p className="text-sm text-gray-400 mt-1">
                                            The highly reliable, standard API used for base match statistics, fixtures, and core standings.
                                        </p>
                                    </div>
                                </div>
                            </label>

                            {/* Option 2: SofaScore / RapidAPI */}
                            <label className={`relative overflow-hidden cursor-pointer border rounded-xl p-4 transition-all ${provider === 'sofascore' ? 'bg-teal-900/30 border-teal-500 shadow-[0_0_15px_rgba(45,212,191,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}>
                                <div className="flex items-start gap-4 relative z-10">
                                    <div className="pt-1">
                                        <input
                                            type="radio"
                                            name="provider"
                                            value="sofascore"
                                            checked={provider === 'sofascore'}
                                            onChange={(e) => setProvider(e.target.value)}
                                            className="w-4 h-4 text-teal-600 bg-gray-700 border-gray-600 focus:ring-teal-500 focus:ring-2"
                                        />
                                    </div>
                                    <div>
                                        <div className="font-bold text-white text-lg flex items-center gap-2">
                                            SofaScore (RapidAPI)
                                            <span className="bg-gradient-to-r from-orange-500 to-amber-500 text-white text-[10px] uppercase font-bold px-2 py-0.5 rounded-full">New</span>
                                        </div>
                                        <div className="text-xs text-orange-400/80 font-medium mb-2 mt-1 uppercase tracking-wider flex items-center gap-1">
                                            <ShieldAlert className="w-3 h-3" /> Experimental
                                        </div>
                                        <p className="text-sm text-gray-400 mt-1">
                                            Aggressive data scraping pipeline bypassing football-data logic entirely to extract deep tactical metrics and advanced team statistics.
                                        </p>
                                    </div>
                                </div>
                            </label>
                        </div>
                    </div>

                    {/* Gemini AI Model Section */}
                    <div className="bg-gray-900/50 p-5 rounded-lg border border-gray-700">
                        <h3 className="text-lg font-semibold text-gray-200 mb-1">Gemini AI Model</h3>
                        <p className="text-sm text-gray-400 mb-4">Select the model used by Agent 1, Agent 2, Agent 3, and the AI Accumulator. Switch here instantly if a model goes down.</p>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {[
                                { value: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro Preview', badge: 'Latest', badgeColor: 'text-blue-400', desc: 'Newest generation Pro model with the latest reasoning improvements.' },
                                { value: 'gemini-3-pro-preview', label: 'Gemini 3 Pro Preview', badge: 'Default', badgeColor: 'text-green-400', desc: 'Current production model. Deep analytical reasoning and Search Grounding support.' },
                                { value: 'gemini-3-flash-preview', label: 'Gemini 3 Flash', badge: 'Fast', badgeColor: 'text-yellow-400', desc: 'Faster responses with lower latency. Good for high-volume analysis runs.' },
                                { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', badge: 'Fast', badgeColor: 'text-yellow-400', desc: 'Previous-gen flash model. Reliable fallback when newer models are unavailable.' },
                            ].map(opt => (
                                <label
                                    key={opt.value}
                                    className={`cursor-pointer border rounded-xl p-4 transition-all ${geminiModel === opt.value ? 'bg-purple-900/30 border-purple-500 shadow-[0_0_15px_rgba(168,85,247,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}
                                >
                                    <div className="flex items-start gap-4">
                                        <div className="pt-1">
                                            <input
                                                type="radio"
                                                name="geminiModel"
                                                value={opt.value}
                                                checked={geminiModel === opt.value}
                                                onChange={(e) => setGeminiModel(e.target.value)}
                                                className="w-4 h-4 text-purple-600 bg-gray-700 border-gray-600 focus:ring-purple-500 focus:ring-2"
                                            />
                                        </div>
                                        <div>
                                            <div className="font-bold text-white">{opt.label}</div>
                                            <div className={`text-xs font-medium mb-2 mt-1 uppercase tracking-wider ${opt.badgeColor}`}>{opt.badge}</div>
                                            <p className="text-sm text-gray-400">{opt.desc}</p>
                                        </div>
                                    </div>
                                </label>
                            ))}
                        </div>
                    </div>

                    {/* Telegram Delivery Mode Section */}
                    <div className="bg-gray-900/50 p-5 rounded-lg border border-gray-700">
                        <h3 className="text-lg font-semibold text-gray-200 mb-4 flex items-center gap-2">
                            <span className="text-[#0088cc]">Telegram</span> Prediction Style
                        </h3>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <label className={`cursor-pointer border rounded-xl p-4 transition-all ${telegramMode === 'text' ? 'bg-blue-900/30 border-blue-500 shadow-[0_0_15px_rgba(59,130,246,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}>
                                <div className="flex items-start gap-3">
                                    <input
                                        type="radio"
                                        name="telegramMode"
                                        value="text"
                                        checked={telegramMode === 'text'}
                                        onChange={(e) => setTelegramMode(e.target.value)}
                                        className="mt-1"
                                    />
                                    <div>
                                        <div className="font-bold text-white">📝 Standard Text</div>
                                        <p className="text-xs text-gray-400 mt-1">Faster delivery with clean Markdown formatting and links.</p>
                                    </div>
                                </div>
                            </label>

                            <label className={`cursor-pointer border rounded-xl p-4 transition-all ${telegramMode === 'image' ? 'bg-indigo-900/30 border-indigo-500 shadow-[0_0_15px_rgba(99,102,241,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}>
                                <div className="flex items-start gap-3">
                                    <input
                                        type="radio"
                                        name="telegramMode"
                                        value="image"
                                        checked={telegramMode === 'image'}
                                        onChange={(e) => setTelegramMode(e.target.value)}
                                        className="mt-1"
                                    />
                                    <div>
                                        <div className="font-bold text-white">🖼️ Elite Card (Image)</div>
                                        <p className="text-xs text-gray-400 mt-1">Premium 1080x1080 social media cards based on your template.</p>
                                    </div>
                                </div>
                            </label>
                        </div>
                    </div>

                    {/* AI Automation Section */}
                    <div className="bg-gray-900/50 p-5 rounded-lg border border-gray-700">
                        <div className="flex items-center justify-between mb-4">
                            <div>
                                <h3 className="text-lg font-semibold text-gray-200">Daily AI Automation</h3>
                                <p className="text-sm text-gray-400">Enable or disable the automatic 2:00 AM analysis cron job.</p>
                            </div>
                            <button
                                onClick={() => setAutomationEnabled(!automationEnabled)}
                                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${automationEnabled ? 'bg-teal-600' : 'bg-gray-700'}`}
                            >
                                <span
                                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${automationEnabled ? 'translate-x-6' : 'translate-x-1'}`}
                                />
                            </button>
                        </div>
                        <div className="flex items-start md:items-center justify-between flex-col md:flex-row gap-4">
                            <div className="flex items-center gap-2 text-xs">
                                <span className={`px-2 py-0.5 rounded-full font-bold uppercase tracking-tighter ${automationEnabled ? 'bg-teal-500/20 text-teal-400 border border-teal-500/30' : 'bg-red-500/20 text-red-400 border border-red-500/30'}`}>
                                    {automationEnabled ? 'Automation Active' : 'Automation Paused'}
                                </span>
                                <span className="text-gray-500 italic">Next run scheduled for 02:00 AM WAT</span>
                            </div>

                            <div className="flex items-center gap-3">
                                {killSignalActive && (
                                    <button
                                        onClick={async () => {
                                            try {
                                                await api.put('/settings/kill-active-cron', { enabled: false });
                                                setKillSignalActive(false);
                                                setMessage({ type: 'success', text: 'Global kill switch reset successfully. Analysis can resume.' });
                                            } catch (err) {
                                                console.error(err);
                                                setMessage({ type: 'error', text: 'Failed to reset kill switch.' });
                                            }
                                        }}
                                        className="bg-green-600/20 hover:bg-green-600 text-green-500 hover:text-white border border-green-500/30 px-3 py-1.5 rounded-md text-xs font-bold transition-all"
                                    >
                                        RESET KILL SWITCH
                                    </button>
                                )}
                                <button
                                    onClick={async () => {
                                        const action = killSignalActive ? "STOPPED" : "ACTIVE";
                                        if (!window.confirm(`This will ${killSignalActive ? 'RESET' : 'TRIGGER'} the global kill switch. If triggered, it will instantly kill all active background analysis. Continue?`)) return;
                                        try {
                                            const newState = !killSignalActive;
                                            await api.put('/settings/kill-active-cron', { enabled: newState });
                                            setKillSignalActive(newState);
                                            setMessage({ type: 'success', text: newState ? 'Emergency stop signal sent to background processes.' : 'Global kill switch reset.' });
                                        } catch (err) {
                                            console.error(err);
                                            setMessage({ type: 'error', text: 'Failed to update kill signal.' });
                                        }
                                    }}
                                    className={`${killSignalActive ? 'bg-amber-600/20 text-amber-500 border-amber-500/30' : 'bg-red-600/20 text-red-500 border-red-500/30'} hover:bg-opacity-100 hover:text-white border px-3 py-1.5 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 group`}
                                >
                                    <ShieldAlert className={`w-3.5 h-3.5 ${killSignalActive ? '' : 'group-hover:animate-pulse'}`} />
                                    {killSignalActive ? 'KILL SWITCH ACTIVE (STOPPED)' : 'TRIGGER EMERGENCY STOP'}
                                </button>
                            </div>
                        </div>
                    </div>

                    <div className="pt-4 border-t border-gray-700 flex justify-end">
                        <button
                            onClick={handleSave}
                            disabled={saving}
                            className="bg-teal-600 hover:bg-teal-500 text-white px-6 py-2 rounded-lg font-medium transition-colors flex items-center gap-2 shadow-lg shadow-teal-900/40"
                        >
                            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                            {saving ? 'Saving...' : 'Save Configuration'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SettingsTab;
