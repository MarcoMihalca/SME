"""
Utilitar desktop Tkinter pentru administrarea utilizatorilor bazei de date SQLite
(`Login/users.db`) partajată cu serverul Web SME.
"""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, Optional

try:
    from . import database
except ImportError:
    import database


class LoginApp:
    """Aplicație Tkinter pentru autentificare, schimbare parolă și gestiune utilizatori."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SME — Autentificare & Gestiune Utilizatori")
        self.root.geometry("680x480")
        self.root.minsize(600, 440)
        self.current_user: Optional[Dict[str, Any]] = None

        try:
            database.create_database()
        except sqlite3.Error as exc:
            messagebox.showerror(
                "Eroare bază de date",
                f"Nu s-a putut inițializa baza de date:\n{exc}",
                parent=self.root,
            )

        self.show_login()

    def clear_window(self) -> None:
        for widget in self.root.winfo_children():
            widget.destroy()

    def show_login(self) -> None:
        self.current_user = None
        self.clear_window()

        frame = tk.Frame(self.root, padx=28, pady=24)
        frame.pack(expand=True, fill="both")

        tk.Label(
            frame,
            text="AUTENTIFICARE SME",
            font=("Segoe UI", 20, "bold"),
        ).pack(pady=(12, 6))

        tk.Label(
            frame,
            text="Eaton NZMH4-PX1600-TAZ (PXR25) — Bază utilizatori partajată",
            font=("Segoe UI", 9),
            fg="#555555",
        ).pack(pady=(0, 20))

        tk.Label(frame, text="Nume utilizator", font=("Segoe UI", 10, "bold")).pack(
            pady=(4, 2)
        )
        username_entry = tk.Entry(frame, width=32, font=("Segoe UI", 11))
        username_entry.pack(pady=(0, 10))
        username_entry.focus_set()

        tk.Label(frame, text="Parolă", font=("Segoe UI", 10, "bold")).pack(
            pady=(4, 2)
        )
        password_entry = tk.Entry(frame, width=32, show="*", font=("Segoe UI", 11))
        password_entry.pack(pady=(0, 16))

        status_var = tk.StringVar(value="")
        status_label = tk.Label(
            frame,
            textvariable=status_var,
            fg="#b91c1c",
            font=("Segoe UI", 9),
            wraplength=420,
        )
        status_label.pack(pady=(0, 10))

        def authenticate(_event: Optional[tk.Event] = None) -> None:
            username = username_entry.get()
            password = password_entry.get()
            try:
                user, message, _ = database.authenticate_user(username, password)
            except sqlite3.Error as exc:
                messagebox.showerror(
                    "Eroare bază de date",
                    f"Eroare la citirea bazei de date:\n{exc}",
                    parent=self.root,
                )
                return

            if user is not None:
                messagebox.showinfo("Succes", message, parent=self.root)
                self.show_dashboard(user)
            else:
                status_var.set(message)
                messagebox.showerror("Eroare", message, parent=self.root)
                password_entry.delete(0, tk.END)
                password_entry.focus_set()

        username_entry.bind("<Return>", lambda _e: password_entry.focus_set())
        password_entry.bind("<Return>", authenticate)

        tk.Button(
            frame,
            text="AUTENTIFICARE",
            width=22,
            height=1,
            font=("Segoe UI", 10, "bold"),
            command=authenticate,
        ).pack(pady=6)

    def show_dashboard(self, user: Dict[str, Any]) -> None:
        self.current_user = user
        self.clear_window()

        frame = tk.Frame(self.root, padx=28, pady=24)
        frame.pack(expand=True, fill="both")

        tk.Label(
            frame,
            text="PANOU UTILIZATOR SME",
            font=("Segoe UI", 19, "bold"),
        ).pack(pady=(16, 14))

        info_box = tk.Frame(frame, bd=1, relief="groove", padx=18, pady=12)
        info_box.pack(pady=(0, 18))

        tk.Label(
            info_box,
            text=f"Utilizator: {user['username']}",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=2)
        tk.Label(
            info_box,
            text=f"Rol: {user['role']}",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=2)
        tk.Label(
            info_box,
            text=f"Ultima autentificare: {user.get('last_login_at') or '—'}",
            font=("Segoe UI", 9),
            fg="#555555",
        ).pack(anchor="w", pady=2)

        if user["role"] == "admin":
            tk.Button(
                frame,
                text="Administrare utilizatori",
                width=26,
                font=("Segoe UI", 10, "bold"),
                command=self.show_users,
            ).pack(pady=6)

        tk.Button(
            frame,
            text="Schimbă parola",
            width=26,
            font=("Segoe UI", 10),
            command=self._open_change_password_dialog,
        ).pack(pady=6)

        tk.Button(
            frame,
            text="Deconectare",
            width=26,
            font=("Segoe UI", 10),
            command=self.show_login,
        ).pack(pady=(12, 4))

    def _open_change_password_dialog(self) -> None:
        if not self.current_user:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Schimbă parola")
        dlg.geometry("360x250")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text="Parola actuală", font=("Segoe UI", 9, "bold")).pack(
            pady=(14, 2)
        )
        cur_entry = tk.Entry(dlg, width=30, show="*")
        cur_entry.pack(pady=(0, 8))
        cur_entry.focus_set()

        tk.Label(dlg, text="Parolă nouă (min. 8 car., literă + cifră)", font=("Segoe UI", 9, "bold")).pack(
            pady=(4, 2)
        )
        new_entry = tk.Entry(dlg, width=30, show="*")
        new_entry.pack(pady=(0, 8))

        tk.Label(dlg, text="Confirmă parola nouă", font=("Segoe UI", 9, "bold")).pack(
            pady=(4, 2)
        )
        conf_entry = tk.Entry(dlg, width=30, show="*")
        conf_entry.pack(pady=(0, 12))

        def submit(_event: Optional[tk.Event] = None) -> None:
            if not self.current_user:
                return
            cur_pw = cur_entry.get()
            new_pw = new_entry.get()
            conf_pw = conf_entry.get()
            if new_pw != conf_pw:
                messagebox.showerror("Eroare", "Parolele noi nu coincid!", parent=dlg)
                return
            try:
                ok, msg = database.change_password(
                    self.current_user["id"], cur_pw, new_pw
                )
            except sqlite3.Error as exc:
                messagebox.showerror("Eroare bază de date", str(exc), parent=dlg)
                return
            if ok:
                messagebox.showinfo("Succes", msg, parent=dlg)
                dlg.destroy()
            else:
                messagebox.showerror("Eroare", msg, parent=dlg)

        conf_entry.bind("<Return>", submit)
        tk.Button(dlg, text="Salvează parola", width=18, command=submit).pack(pady=4)

    def show_users(self) -> None:
        if not self.current_user or self.current_user.get("role") != "admin":
            self.show_login()
            return

        self.clear_window()
        actor_name = str(self.current_user["username"])
        actor_id = int(self.current_user["id"])

        tk.Label(
            self.root,
            text="ADMINISTRARE UTILIZATORI",
            font=("Segoe UI", 16, "bold"),
        ).pack(pady=(14, 8))

        table_frame = tk.Frame(self.root, padx=16)
        table_frame.pack(fill="both", expand=True, pady=(0, 8))

        tree = ttk.Treeview(
            table_frame,
            columns=("ID", "Username", "Rol", "Activ", "Ultima autentificare"),
            show="headings",
            height=10,
        )
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.heading("ID", text="ID")
        tree.heading("Username", text="Utilizator")
        tree.heading("Rol", text="Rol")
        tree.heading("Activ", text="Activ")
        tree.heading("Ultima autentificare", text="Ultima autentificare")

        tree.column("ID", width=45, anchor="center")
        tree.column("Username", width=165)
        tree.column("Rol", width=85, anchor="center")
        tree.column("Activ", width=75, anchor="center")
        tree.column("Ultima autentificare", width=190, anchor="center")

        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        users_by_id: Dict[int, Dict[str, Any]] = {}

        def refresh_users() -> None:
            for item in tree.get_children():
                tree.delete(item)
            users_by_id.clear()
            try:
                rows = database.list_users_detailed()
            except sqlite3.Error as exc:
                messagebox.showerror("Eroare bază de date", str(exc), parent=self.root)
                return
            for u in rows:
                users_by_id[u["id"]] = u
                active_lbl = "Blocat" if u["is_locked"] else ("Da" if u["is_active"] else "Nu")
                last_login = u["last_login_at"] or "—"
                tree.insert(
                    "",
                    "end",
                    values=(u["id"], u["username"], u["role"], active_lbl, last_login),
                )

        def _get_selected_user() -> Optional[Dict[str, Any]]:
            selected = tree.selection()
            if not selected:
                messagebox.showwarning(
                    "Atenție", "Selectează un utilizator din listă!", parent=self.root
                )
                return None
            values = tree.item(selected[0], "values")
            uid = int(values[0])
            return users_by_id.get(uid)

        def add_user() -> None:
            dlg = tk.Toplevel(self.root)
            dlg.title("Adaugă utilizator")
            dlg.geometry("360x260")
            dlg.resizable(False, False)
            dlg.transient(self.root)
            dlg.grab_set()

            tk.Label(dlg, text="Nume utilizator (3–32 car.)", font=("Segoe UI", 9, "bold")).pack(
                pady=(14, 2)
            )
            u_entry = tk.Entry(dlg, width=30)
            u_entry.pack(pady=(0, 8))
            u_entry.focus_set()

            tk.Label(dlg, text="Parolă (min. 8 car., literă + cifră)", font=("Segoe UI", 9, "bold")).pack(
                pady=(4, 2)
            )
            p_entry = tk.Entry(dlg, width=30, show="*")
            p_entry.pack(pady=(0, 8))

            role_var = tk.StringVar(value="user")
            role_frame = tk.Frame(dlg)
            role_frame.pack(pady=(4, 10))
            tk.Label(role_frame, text="Rol:", font=("Segoe UI", 9, "bold")).pack(
                side="left", padx=(0, 8)
            )
            tk.Radiobutton(role_frame, text="user", variable=role_var, value="user").pack(
                side="left", padx=4
            )
            tk.Radiobutton(role_frame, text="admin", variable=role_var, value="admin").pack(
                side="left", padx=4
            )

            def submit_add(_event: Optional[tk.Event] = None) -> None:
                try:
                    ok, msg = database.register_user(
                        u_entry.get(), p_entry.get(), role_var.get(), actor=actor_name
                    )
                except sqlite3.Error as exc:
                    messagebox.showerror("Eroare bază de date", str(exc), parent=dlg)
                    return
                if ok:
                    messagebox.showinfo("Succes", msg, parent=dlg)
                    dlg.destroy()
                    refresh_users()
                else:
                    messagebox.showerror("Eroare", msg, parent=dlg)

            p_entry.bind("<Return>", submit_add)
            tk.Button(dlg, text="Creează cont", width=18, command=submit_add).pack(pady=4)

        def toggle_role() -> None:
            target = _get_selected_user()
            if not target:
                return
            next_role = "user" if target["role"] == "admin" else "admin"
            try:
                ok, msg = database.update_user(
                    target["id"],
                    role=next_role,
                    actor=actor_name,
                    actor_id=actor_id,
                )
            except sqlite3.Error as exc:
                messagebox.showerror("Eroare bază de date", str(exc), parent=self.root)
                return
            if ok:
                messagebox.showinfo("Succes", msg, parent=self.root)
                refresh_users()
            else:
                messagebox.showerror("Eroare", msg, parent=self.root)

        def toggle_active() -> None:
            target = _get_selected_user()
            if not target:
                return
            next_active = not bool(target["is_active"])
            unlock = bool(target["is_locked"])
            try:
                ok, msg = database.update_user(
                    target["id"],
                    is_active=next_active,
                    unlock=unlock,
                    actor=actor_name,
                    actor_id=actor_id,
                )
            except sqlite3.Error as exc:
                messagebox.showerror("Eroare bază de date", str(exc), parent=self.root)
                return
            if ok:
                messagebox.showinfo("Succes", msg, parent=self.root)
                refresh_users()
            else:
                messagebox.showerror("Eroare", msg, parent=self.root)

        def reset_selected_password() -> None:
            target = _get_selected_user()
            if not target:
                return
            dlg = tk.Toplevel(self.root)
            dlg.title(f"Resetare parolă — {target['username']}")
            dlg.geometry("350x160")
            dlg.resizable(False, False)
            dlg.transient(self.root)
            dlg.grab_set()

            tk.Label(
                dlg,
                text="Parolă nouă (min. 8 car., literă + cifră)",
                font=("Segoe UI", 9, "bold"),
            ).pack(pady=(16, 4))
            np_entry = tk.Entry(dlg, width=30, show="*")
            np_entry.pack(pady=(0, 12))
            np_entry.focus_set()

            def submit_reset(_event: Optional[tk.Event] = None) -> None:
                try:
                    ok, msg = database.reset_password(
                        target["id"], np_entry.get(), actor=actor_name
                    )
                except sqlite3.Error as exc:
                    messagebox.showerror("Eroare bază de date", str(exc), parent=dlg)
                    return
                if ok:
                    messagebox.showinfo("Succes", msg, parent=dlg)
                    dlg.destroy()
                    refresh_users()
                else:
                    messagebox.showerror("Eroare", msg, parent=dlg)

            np_entry.bind("<Return>", submit_reset)
            tk.Button(dlg, text="Resetează parola", width=18, command=submit_reset).pack()

        def remove_user() -> None:
            target = _get_selected_user()
            if not target:
                return
            if not messagebox.askyesno(
                "Confirmare",
                f"Sigur vrei să ștergi utilizatorul '{target['username']}'?",
                parent=self.root,
            ):
                return
            try:
                ok, msg = database.delete_user_checked(
                    target["id"], actor=actor_name, actor_id=actor_id
                )
            except sqlite3.Error as exc:
                messagebox.showerror("Eroare bază de date", str(exc), parent=self.root)
                return
            if ok:
                messagebox.showinfo("Succes", msg, parent=self.root)
                refresh_users()
            else:
                messagebox.showerror("Eroare", msg, parent=self.root)

        btn_row1 = tk.Frame(self.root)
        btn_row1.pack(pady=4)
        tk.Button(btn_row1, text="Adaugă utilizator", width=18, command=add_user).pack(
            side="left", padx=4
        )
        tk.Button(btn_row1, text="Comută rol", width=16, command=toggle_role).pack(
            side="left", padx=4
        )
        tk.Button(
            btn_row1, text="Activează / Dezactivează", width=22, command=toggle_active
        ).pack(side="left", padx=4)

        btn_row2 = tk.Frame(self.root)
        btn_row2.pack(pady=(4, 14))
        tk.Button(
            btn_row2, text="Resetează parolă", width=18, command=reset_selected_password
        ).pack(side="left", padx=4)
        tk.Button(btn_row2, text="Șterge utilizator", width=16, command=remove_user).pack(
            side="left", padx=4
        )
        tk.Button(
            btn_row2,
            text="Înapoi la panou",
            width=22,
            command=lambda: self.show_dashboard(self.current_user or {"username": actor_name, "role": "admin", "id": actor_id}),
        ).pack(side="left", padx=4)

        refresh_users()


def main() -> None:
    root = tk.Tk()
    LoginApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
