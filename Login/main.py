
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import database


# Fereastra principală
root = tk.Tk()
root.title("Sistem Login - Python")
root.geometry("500x400")
root.resizable(False, False)


def clear_window():
    for widget in root.winfo_children():
        widget.destroy()


# Fereastra de autentificare
def show_login():

    clear_window()

    tk.Label(
        root,
        text="AUTENTIFICARE",
        font=("Arial", 22, "bold")
    ).pack(pady=25)

    tk.Label(root, text="Nume utilizator").pack()

    username_entry = tk.Entry(root, width=30)
    username_entry.pack(pady=5)

    tk.Label(root, text="Parolă").pack()

    password_entry = tk.Entry(root, width=30, show="*")
    password_entry.pack(pady=5)

    def authenticate():

        username = username_entry.get()
        password = password_entry.get()

        user = database.login_user(username, password)

        if user:
            messagebox.showinfo(
                "Succes",
                "Autentificare reușită!"
            )

            show_dashboard(user)

        else:
            messagebox.showerror(
                "Eroare",
                "Nume sau parolă incorectă!"
            )

    tk.Button(
        root,
        text="LOGIN",
        width=20,
        command=authenticate
    ).pack(pady=20)


# Panoul principal
def show_dashboard(user):

    clear_window()

    tk.Label(
        root,
        text="BINE AI VENIT!",
        font=("Arial", 22, "bold")
    ).pack(pady=20)

    tk.Label(
        root,
        text=f"Utilizator: {user['username']}"
    ).pack(pady=5)

    tk.Label(
        root,
        text=f"Rol: {user['role']}"
    ).pack(pady=5)

    # Administratorul poate gestiona utilizatorii
    if user["role"] == "admin":

        tk.Button(
            root,
            text="Administrare utilizatori",
            width=25,
            command=show_users
        ).pack(pady=20)

    tk.Button(
        root,
        text="Deconectare",
        width=20,
        command=show_login
    ).pack(pady=10)


# Fereastra de administrare utilizatori
def show_users():

    clear_window()

    tk.Label(
        root,
        text="ADMINISTRARE UTILIZATORI",
        font=("Arial", 18, "bold")
    ).pack(pady=15)

    tree = ttk.Treeview(
        root,
        columns=("ID", "Username", "Rol"),
        show="headings",
        height=8
    )

    tree.heading("ID", text="ID")
    tree.heading("Username", text="Utilizator")
    tree.heading("Rol", text="Rol")

    tree.column("ID", width=50)
    tree.column("Username", width=200)
    tree.column("Rol", width=100)

    tree.pack(pady=10)

    def refresh_users():

        for item in tree.get_children():
            tree.delete(item)

        for user in database.get_users():
            tree.insert("", "end", values=user)

    def add_user():

        username = simpledialog.askstring(
            "Utilizator nou",
            "Introdu numele utilizatorului:"
        )

        if username is None:
            return

        password = simpledialog.askstring(
            "Parolă",
            "Introdu parola:",
            show="*"
        )

        if password is None:
            return

        success, message = database.register_user(
            username,
            password,
            "user"
        )

        if success:
            messagebox.showinfo("Succes", message)
        else:
            messagebox.showerror("Eroare", message)

        refresh_users()

    def remove_user():

        selected = tree.selection()

        if not selected:
            messagebox.showwarning(
                "Atenție",
                "Selectează un utilizator!"
            )
            return

        values = tree.item(selected[0], "values")
        user_id = int(values[0])

        if messagebox.askyesno(
            "Confirmare",
            "Sigur vrei să ștergi utilizatorul?"
        ):
            if database.delete_user(user_id):
                messagebox.showinfo(
                    "Succes",
                    "Utilizator șters!"
                )
            else:
                messagebox.showerror(
                    "Eroare",
                    "Utilizatorul nu poate fi șters!"
                )

            refresh_users()

    tk.Button(
        root,
        text="Adaugă utilizator",
        command=add_user
    ).pack(pady=5)

    tk.Button(
        root,
        text="Șterge utilizator",
        command=remove_user
    ).pack(pady=5)

    tk.Button(
        root,
        text="Înapoi",
        command=show_login
    ).pack(pady=10)

    refresh_users()


# Inițializare aplicație
database.create_database()
show_login()

root.mainloop()
