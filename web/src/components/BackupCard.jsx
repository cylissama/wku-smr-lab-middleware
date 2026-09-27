import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../api/apiClient";

export default function BackupCard({sendMessage}) {

    const boxRef = useRef(null);
    const [backupFiles, setBackupFiles] = useState([]);
    const [refreshBool, setRefreshBool] = useState(false);
    const [backuping, setBackuping] = useState(false);
    const [isRecovering, setIsRecovering] = useState(false);

    useEffect(() => {
            boxRef.current?.scrollTo({
                top: boxRef.current.scrollHeight,
                behavior: "auto",
            });
    }, [backupFiles]);

    useEffect(() => {
        fetchBackups();
    }, []);

    useEffect(() => {
        fetchBackups();
    }, [refreshBool]);

    const fetchBackups = async () => {
        try {
            sendMessage("misc", "info", "Fetching Backups...");

            const data = await apiGet("/backup/list");
            setBackupFiles(data.files);

        } catch (err) {
            sendMessage("misc", "error", "An Unknown Error Occurred: " + err);
        }
    };

    const restoreBackup = async (filepath) => {

        setIsRecovering(true);

        sendMessage(
                    "misc",
                    "info",
                    "DB Backup Recovery Started..."
                );

        try {

            const data = await apiPost(`/backup/restore/${encodeURIComponent(filepath)}`);

            if (data.success) {
                sendMessage("misc", "info", "Loaded Backup Sucessfully");
            } else {
                sendMessage("misc", "error", "Failed to load backup: " + data.error);
            }
        }

        catch (err) {
            sendMessage("misc", "error", "An Unknown Error Occurred: " + err);
        }
        finally{
            setIsRecovering(false);
        }
    }

    const createBackup = async () => {
        setBackuping(true);

        try {
            sendMessage("misc", "info", "Manually creating a backup...");

            const data = await apiGet("/backup");

            if (data.success) {
                sendMessage("misc", "info", "Backup created successfully!");
            } else {
                sendMessage("misc", "error", "Backup failed: " + data.error);
            }

            // refresh list
            setRefreshBool((prev) => !prev);

        } catch (err) {
            sendMessage("misc", "error", "An Unknown Error Occurred: " + err);
        } finally {
            setBackuping(false);
        }
    };

    function BackupInfo ({name}) {

        return (
            <div className="flex flex-row justify-between items-center">
                <h3 className="font-mono text-sm"> {name} </h3>

                <button
                    className="flex items-center gap-1 text-white bg-yellow-500 hover:bg-yellow-600 text-sm px-2 py-1 rounded font-semibold leading-tight cursor-pointer active:scale-95 transition-transform duration-100 disabled:bg-gray-400 disabled:cursor-not-allowed"
                    onClick={() => {restoreBackup(name)}}
                    disabled={isRecovering}
                    >
                    Recover
                </button>
            </div>
        )
    }


    return (
        <div className="bg-white rounded-lg shadow p-5 w-[550px] gap-2">
                <h3 className="text-lg font-semibold mb-2"> Backups</h3>
                
                <div
                    ref={boxRef}
                    className="bg-gray-900 font-mono text-sm text-white rounded-md p-3 h-64 overflow-y-auto overflow-x-auto space-y-3 whitespace-pre text-left w-full"
                >
                    
                    {backupFiles.map((file) => (
                        <BackupInfo key={file} name={file} />
                    ))}



                </div>

                <div className="flex flex-row justify-between items-center">
                    <button
                        className="flex items-center gap-1 text-white bg-blue-500 hover:bg-blue-600 text-sm px-2 py-1 mt-4 rounded font-semibold leading-tight cursor-pointer active:scale-95 transition-transform duration-100 disabled:bg-gray-400 disabled:cursor-not-allowed"
                        onClick={() => {createBackup()}}
                        disabled={backuping}
                        >
                        Create Backup
                    </button>

                    <button
                        className="flex items-center gap-1 text-white bg-blue-500 hover:bg-blue-600 text-sm px-2 py-1 mt-4 rounded font-semibold leading-tight cursor-pointer active:scale-95 transition-transform duration-100 disabled:bg-gray-400 disabled:cursor-not-allowed"
                        onClick={() => {setRefreshBool(!refreshBool)}}
                        >
                        Refresh
                    </button>
                </div>

        </div>
    )
}
