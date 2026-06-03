import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image, ImageTk
import json
import os
import re
import sys
import difflib
import math

class ContextViewer(tk.Toplevel):
    """Popup overlay that shows the full page image, centered on the active polygon."""
    def __init__(self, parent_app, img_path, poly_json, coord_scale):
        super().__init__(parent_app.root)
        self.title("Full Page Context - Release ALT to close")
        
        self.target_w = int(self.winfo_screenwidth() * 0.7)
        self.target_h = int(self.winfo_screenheight() * 0.8)
        self.geometry(f"{self.target_w}x{self.target_h}")
        self.transient(parent_app.root) 
        
        self.canvas = tk.Canvas(self, bg="#222", cursor="fleur")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.poly_json = poly_json
        self.coord_scale = coord_scale
        self.scale = 1.0 
        
        self.base_img = Image.open(img_path).convert("RGB")
        self.draw_image()

        self.canvas.bind("<ButtonPress-1>", self.start_pan)
        self.canvas.bind("<B1-Motion>", self.do_pan)
        self.bind("<MouseWheel>", self.do_zoom)
        self.bind("<Button-4>", self.do_zoom) 
        self.bind("<Button-5>", self.do_zoom) 

        close_cmd = lambda e: parent_app.hide_context_viewer()
        self.bind("<KeyRelease-Alt_L>", close_cmd)
        self.bind("<KeyRelease-Alt_R>", close_cmd)
        self.canvas.bind("<KeyRelease-Alt_L>", close_cmd)
        self.canvas.bind("<KeyRelease-Alt_R>", close_cmd)
        self.bind("<FocusOut>", close_cmd) 

        self.after(20, self.center_on_poly)

    def draw_image(self):
        new_w = int(self.base_img.width * self.scale)
        new_h = int(self.base_img.height * self.scale)
        if new_w <= 0 or new_h <= 0: return
        
        resized = self.base_img.resize((new_w, new_h), Image.BILINEAR)
        self.photo = ImageTk.PhotoImage(resized)
        
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        self.canvas.config(scrollregion=(0, 0, new_w, new_h))
        
        factor = (1.0 / self.coord_scale) * self.scale
        coords = []
        for p in self.poly_json:
            coords.extend([p[0] * factor, p[1] * factor])
            
        if coords:
            self.canvas.create_polygon(coords, outline="black", width=8, fill="") 
            self.canvas.create_polygon(coords, outline="red", width=4, fill="")
            
        self.center_on_poly()

    def center_on_poly(self):
        if not self.poly_json: return
        self.canvas.update_idletasks() 
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            cw = self.target_w
            ch = self.target_h
        
        factor = (1.0 / self.coord_scale) * self.scale
        xs = [p[0] * factor for p in self.poly_json]
        ys = [p[1] * factor for p in self.poly_json]
        
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        
        scroll_w = self.base_img.width * self.scale
        scroll_h = self.base_img.height * self.scale
        
        frac_x = max(0.0, (cx - (cw / 2.0)) / scroll_w)
        frac_y = max(0.0, (cy - (ch / 2.0)) / scroll_h)
        
        self.canvas.xview_moveto(frac_x)
        self.canvas.yview_moveto(frac_y)

    def start_pan(self, event): self.canvas.scan_mark(event.x, event.y)
    def do_pan(self, event): self.canvas.scan_dragto(event.x, event.y, gain=1)
    def do_zoom(self, event):
        if event.num == 4 or event.delta > 0: self.scale *= 1.2
        elif event.num == 5 or event.delta < 0: self.scale /= 1.2
        self.draw_image()

class OCREditorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NCBS Pipeline Editor")
        self.root.geometry("1400x850")

        self.json_data = [] 
        self.image_paths = []
        self.current_page_idx = 0
        self.current_line_idx = 0 
        self.active_text_widget = None 
        self.line_widgets = [] 
        self.viewer_window = None 
        
        self.job_dir = None
        self.json_folder_path = None 

        self.setup_ui()
        self.setup_hotkeys()
        
        if len(sys.argv) > 1:
            self.load_job_directory(sys.argv[1])

    @staticmethod
    def extract_res(data):
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and "res" in data[0]:
            return data[0]["res"]
        if isinstance(data, dict):
            return data.get("res", data)
        return data

    def get_res_node(self, page_idx):
        return self.extract_res(self.json_data[page_idx]["data"])

    def setup_ui(self):
        control_frame = tk.Frame(self.root, pady=5)
        control_frame.pack(side=tk.TOP, fill=tk.X, padx=10)

        # --- ROW 1: File Operations & Export ---
        row1 = tk.Frame(control_frame)
        row1.pack(side=tk.TOP, fill=tk.X, pady=5)

        tk.Button(row1, text="📂 Load Job Directory", command=self.prompt_job_directory, font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)
        
        tk.Button(row1, text="Save JSONs", command=self.save_json, fg="blue").pack(side=tk.LEFT, padx=5)
        self.auto_save_var = tk.BooleanVar(value=True)
        tk.Checkbutton(row1, text="💾 Auto-Save", variable=self.auto_save_var, fg="blue").pack(side=tk.LEFT)
        
        tk.Label(row1, text=" | ", fg="gray").pack(side=tk.LEFT)
        
        tk.Button(row1, text="Export TXT", command=self.export_txt).pack(side=tk.LEFT, padx=5)
        tk.Button(row1, text="Export Diff (HTML)", command=self.export_diff_html, fg="purple").pack(side=tk.LEFT, padx=5)
        
        self.remove_hyphens_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row1, text="Merge Hyphenated Words", variable=self.remove_hyphens_var).pack(side=tk.LEFT)

        tk.Label(row1, text=" | Skip Top:").pack(side=tk.LEFT)
        self.skip_top_var = tk.IntVar(value=0)
        tk.Entry(row1, textvariable=self.skip_top_var, width=3).pack(side=tk.LEFT)

        tk.Label(row1, text=" Bot:").pack(side=tk.LEFT)
        self.skip_bottom_var = tk.IntVar(value=0)
        tk.Entry(row1, textvariable=self.skip_bottom_var, width=3).pack(side=tk.LEFT)

        tk.Button(row1, text="Next Page ►", command=self.next_page).pack(side=tk.RIGHT, padx=5)
        tk.Button(row1, text="◄ Prev Page", command=self.prev_page).pack(side=tk.RIGHT, padx=5)
        
        self.status_var = tk.StringVar(value="Not Started")
        status_dropdown = ttk.Combobox(row1, textvariable=self.status_var, values=["🔴 Not Started", "🟡 Reviewing", "🟢 Completed"], width=15, state="readonly")
        status_dropdown.pack(side=tk.RIGHT, padx=10)
        status_dropdown.bind("<<ComboboxSelected>>", self.on_status_change)
        tk.Label(row1, text="Status:").pack(side=tk.RIGHT)

        # --- ROW 2: View Settings ---
        row2 = tk.Frame(control_frame)
        row2.pack(side=tk.TOP, fill=tk.X, pady=5)

        tk.Label(row2, text="Coord Scale:").pack(side=tk.LEFT, padx=(5, 2))
        self.scale_var = tk.DoubleVar(value=1.0) 
        tk.Entry(row2, textvariable=self.scale_var, width=6).pack(side=tk.LEFT)

        tk.Label(row2, text=" | Pad:").pack(side=tk.LEFT, padx=(10, 2))
        self.padding_var = tk.IntVar(value=10)
        tk.Entry(row2, textvariable=self.padding_var, width=3).pack(side=tk.LEFT)

        tk.Label(row2, text=" | UI Zoom:").pack(side=tk.LEFT, padx=(10, 2))
        self.ui_zoom_var = tk.DoubleVar(value=1.0) 
        tk.Entry(row2, textvariable=self.ui_zoom_var, width=4).pack(side=tk.LEFT)

        tk.Label(row2, text=" | Font Size:").pack(side=tk.LEFT, padx=(10, 2))
        self.font_size_var = tk.IntVar(value=16) 
        tk.Entry(row2, textvariable=self.font_size_var, width=3).pack(side=tk.LEFT)

        tk.Button(row2, text="Apply View", command=self.refresh_view).pack(side=tk.LEFT, padx=10)

        tk.Label(row2, text=" | Layout:").pack(side=tk.LEFT, padx=(15, 2))
        self.side_by_side_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row2, text="Side-by-Side (Vertical)", variable=self.side_by_side_var, command=self.refresh_view).pack(side=tk.LEFT)

        tk.Label(row2, text="💡 Hold [ALT] for context  |  Ctrl+Right/Left for Pages", fg="#888", font=("Arial", 10, "italic")).pack(side=tk.RIGHT, padx=15)
        self.page_label = tk.Label(row2, text="Page: 0/0", font=("Helvetica", 10, "bold"))
        self.page_label.pack(side=tk.RIGHT, padx=20)

        # --- ROW 3: Edit Mode ---
        row3 = tk.Frame(control_frame)
        row3.pack(side=tk.TOP, fill=tk.X, pady=2)
        
        tk.Label(row3, text="Edit Mode:", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(5, 10))
        self.edit_mode_var = tk.StringVar(value="All Lines")
        
        tk.Radiobutton(row3, text="All Lines", variable=self.edit_mode_var, value="All Lines", command=self.on_mode_switch).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(row3, text="Speed Mode", variable=self.edit_mode_var, value="Speed Mode", command=self.on_mode_switch).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(row3, text="Low Confidence Mode", variable=self.edit_mode_var, value="Low Conf", command=self.on_mode_switch, fg="#b8860b").pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(row3, text="Full Page Mode", variable=self.edit_mode_var, value="Full Page", command=self.on_mode_switch, fg="purple").pack(side=tk.LEFT, padx=5)

        tk.Button(row3, text="↺ Revert Page to Original Gemini/OCR", command=self.revert_page, fg="red").pack(side=tk.RIGHT, padx=15)

        # --- Main Scrollable Canvas ---
        self.canvas_frame = tk.Frame(self.root)
        self.canvas_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.canvas_frame, bg="#e8e8e8")
        self.scrollbar = ttk.Scrollbar(self.canvas_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg="#e8e8e8")

        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((self.root.winfo_width()//2, 0), window=self.scrollable_frame, anchor="n")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfig(1, width=e.width))

    def setup_hotkeys(self):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel) 
        self.canvas.bind_all("<Button-5>", self._on_mousewheel) 

        self.root.bind("<KeyPress-Alt_L>", self.show_context_viewer)
        self.root.bind("<KeyRelease-Alt_L>", self.hide_context_viewer)
        self.root.bind("<KeyPress-Alt_R>", self.show_context_viewer)
        self.root.bind("<KeyRelease-Alt_R>", self.hide_context_viewer)
        
        self.root.bind("<Control-Right>", lambda e: self.next_page())
        self.root.bind("<Control-Left>", lambda e: self.prev_page())
        self.root.bind("<Next>", lambda e: self.next_page()) 
        self.root.bind("<Prior>", lambda e: self.prev_page()) 

    def _on_mousewheel(self, event):
        if event.num == 4 or event.delta > 0: self.canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0: self.canvas.yview_scroll(1, "units")

    def show_context_viewer(self, event=None):
        if self.viewer_window is None and self.json_data and self.image_paths:
            if self.current_page_idx < len(self.image_paths):
                img_path = self.image_paths[self.current_page_idx]
                res_node = self.get_res_node(self.current_page_idx)
                rec_polys = res_node.get('rec_polys', [])
                
                if rec_polys:
                    if self.edit_mode_var.get() == "Full Page" and self.active_text_widget:
                        try:
                            cursor_pos = self.active_text_widget.index(tk.INSERT)
                            text_line = int(cursor_pos.split('.')[0]) - 1
                            self.current_line_idx = max(0, min(text_line, len(rec_polys) - 1))
                        except Exception: pass

                    idx = min(self.current_line_idx, len(rec_polys) - 1)
                    poly = rec_polys[idx]
                    coord_scale = max(0.01, self.scale_var.get())
                    self.viewer_window = ContextViewer(self, img_path, poly, coord_scale)

    def hide_context_viewer(self, event=None):
        if self.viewer_window is not None:
            self.viewer_window.destroy()
            self.viewer_window = None

    def get_smart_start_line(self):
        if not self.json_data: return 0
        res_node = self.get_res_node(self.current_page_idx)
        
        if self.edit_mode_var.get() == "Low Conf":
            lc_indices = res_node.get('low_conf_indices', {})
            for idx in sorted(lc_indices.keys()):
                if not res_node.get('reviewed_lines', [])[idx]:
                    return idx
            return 0
        else:
            reviewed_lines = res_node.get('reviewed_lines', [])
            try: return reviewed_lines.index(False) 
            except ValueError: return 0 

    def set_active_line(self, index):
        self.current_line_idx = index
        if self.json_data:
            self.get_res_node(self.current_page_idx)["last_active_line"] = index

    def update_page_status(self):
        if not self.json_data: return
        res_node = self.get_res_node(self.current_page_idx)
        reviewed_lines = res_node.get('reviewed_lines', [])
        
        if not reviewed_lines: return
            
        if all(reviewed_lines): new_status = "🟢 Completed"
        elif any(reviewed_lines): new_status = "🟡 Reviewing"
        else: new_status = "🔴 Not Started"
            
        res_node["page_status"] = new_status
        self.status_var.set(new_status)

    def mark_line_reviewed(self, index):
        if self.json_data:
            res_node = self.get_res_node(self.current_page_idx)
            if 'reviewed_lines' in res_node and index < len(res_node['reviewed_lines']):
                res_node['reviewed_lines'][index] = True
            self.update_page_status()

    def scroll_to_widget(self, widget):
        self.canvas.update_idletasks()
        widget_y = widget.winfo_y() 
        frame_height = self.scrollable_frame.winfo_height()
        if frame_height > 0:
            fraction = widget_y / frame_height
            self.canvas.yview_moveto(max(0.0, fraction - 0.1)) 

    def advance_line(self, event=None):
        self.mark_line_reviewed(self.current_line_idx)
        res_node = self.get_res_node(self.current_page_idx)
        target_texts = res_node.get('gemini_rec_texts', res_node.get('rec_texts', []))
        
        if self.edit_mode_var.get() == "Low Conf":
            lc_indices = res_node.get('low_conf_indices', {})
            next_idx = None
            for idx in sorted(lc_indices.keys()):
                if idx > self.current_line_idx:
                    next_idx = idx
                    break
            if next_idx is not None:
                self.set_active_line(next_idx)
                self.refresh_view()
            else:
                self.next_page()
            return "break"
            
        elif self.edit_mode_var.get() == "Speed Mode":
            if self.current_line_idx < len(target_texts) - 1:
                self.set_active_line(self.current_line_idx + 1)
                self.refresh_view()
            else:
                self.next_page()
            return "break"
            
        else:
            if self.current_line_idx < len(target_texts) - 1:
                self.set_active_line(self.current_line_idx + 1)
                if self.current_line_idx < len(self.line_widgets):
                    next_widget = self.line_widgets[self.current_line_idx]
                    next_widget.focus_set()
                    self.scroll_to_widget(next_widget)
            else:
                self.next_page()
            return "break"

    def previous_line(self, event=None):
        res_node = self.get_res_node(self.current_page_idx)
        target_texts = res_node.get('gemini_rec_texts', res_node.get('rec_texts', []))

        if self.edit_mode_var.get() == "Low Conf":
            lc_indices = res_node.get('low_conf_indices', {})
            prev_idx = None
            for idx in sorted(lc_indices.keys(), reverse=True):
                if idx < self.current_line_idx:
                    prev_idx = idx
                    break
            if prev_idx is not None:
                self.set_active_line(prev_idx)
                self.refresh_view()
            else:
                self.prev_page()
            return "break"

        elif self.edit_mode_var.get() == "Speed Mode":
            if self.current_line_idx > 0:
                self.set_active_line(self.current_line_idx - 1)
                self.refresh_view()
            else:
                self.prev_page()
            return "break"
        else:
            if self.current_line_idx > 0:
                self.set_active_line(self.current_line_idx - 1)
                if self.current_line_idx < len(self.line_widgets):
                    prev_widget = self.line_widgets[self.current_line_idx]
                    prev_widget.focus_set()
                    self.scroll_to_widget(prev_widget)
            else:
                self.prev_page()
            return "break"

    def on_mode_switch(self):
        self.current_line_idx = self.get_smart_start_line()
        self.refresh_view()

    def on_status_change(self, event=None):
        if self.json_data:
            self.get_res_node(self.current_page_idx)["page_status"] = self.status_var.get()

    def revert_page(self):
        if not self.json_data: return
        if messagebox.askyesno("Confirm Revert", "Are you sure you want to delete all edits on this page and restore the original AI text?"):
            res_node = self.get_res_node(self.current_page_idx)
            if 'original_texts' in res_node:
                if 'gemini_rec_texts' in res_node:
                    res_node['gemini_rec_texts'] = list(res_node['original_texts'])
                else:
                    res_node['rec_texts'] = list(res_node['original_texts'])
                    
                res_node['rec_polys'] = list(res_node.get('original_polys', res_node.get('rec_polys', [])))
                res_node['reviewed_lines'] = [False] * len(res_node['original_texts'])
                
                self.update_page_status()
                self.current_line_idx = 0
                self.refresh_view()

    def prompt_job_directory(self):
        job_dir = filedialog.askdirectory(title="Select Job Directory")
        if job_dir:
            self.load_job_directory(job_dir)

    def load_job_directory(self, job_dir):
        self.job_dir = job_dir
        pages_dir = os.path.join(job_dir, "pages")
        merged_dir = os.path.join(job_dir, "merged")

        if not os.path.exists(pages_dir) or not os.path.exists(merged_dir):
            messagebox.showwarning("Error", "Could not find 'pages' or 'merged' folders in the selected Job Directory.")
            return

        self.json_folder_path = merged_dir

        valid_exts = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif')
        img_files = [f for f in os.listdir(pages_dir) if f.lower().endswith(valid_exts)]
        img_files.sort(key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0)
        self.image_paths = [os.path.join(pages_dir, f) for f in img_files]

        self.json_data = []
        for filename in os.listdir(merged_dir):
            if filename.lower().endswith('.json'):
                full_path = os.path.join(merged_dir, filename)
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                        res_node = self.extract_res(data)
                        if not isinstance(res_node, dict): continue

                        if "page_status" not in res_node: res_node["page_status"] = "🔴 Not Started"
                            
                        if 'gemini_rec_texts' in res_node:
                            target_texts = res_node['gemini_rec_texts']
                        else:
                            target_texts = res_node.get('rec_texts', [])
                            
                        if 'original_texts' not in res_node:
                            res_node['original_texts'] = list(target_texts)
                            res_node['original_polys'] = list(res_node.get('rec_polys', []))
                            
                        if 'reviewed_lines' not in res_node:
                            res_node['reviewed_lines'] = [False] * len(target_texts)
                            
                        lc_list = res_node.get('low_confidence', [])
                        res_node['low_conf_indices'] = {item['i']: item.get('why', 'Low Confidence') for item in lc_list}
                            
                        self.json_data.append({"filepath": full_path, "filename": filename, "data": data})
                except Exception as e:
                    print(f"Error loading {filename}: {e}")

        def get_page_sort_key(item):
            res_node = self.extract_res(item["data"])
            idx = res_node.get("page_index")
            if idx is not None: return idx
            match = re.search(r'\d+', item["filename"])
            return int(match.group()) if match else 0

        self.json_data.sort(key=get_page_sort_key)
        self.current_page_idx = 0
        
        if not self.json_data:
            messagebox.showwarning("Warning", "No JSON files loaded.")
            return

        self.current_line_idx = self.get_smart_start_line()
        self.refresh_view()

    def silent_auto_save(self):
        if not self.json_data or not self.json_folder_path or not self.auto_save_var.get(): return
        try:
            for item in self.json_data:
                with open(item["filepath"], 'w', encoding='utf-8') as f:
                    json.dump(item["data"], f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Auto-save failed: {e}")

    def save_json(self):
        if not self.json_data: return
        output_folder = filedialog.askdirectory(title="Select Output Folder", initialdir=self.json_folder_path)
        if not output_folder: return

        try:
            for item in self.json_data:
                out_path = os.path.join(output_folder, item["filename"])
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(item["data"], f, ensure_ascii=False, indent=4)
            messagebox.showinfo("Success", f"Saved {len(self.json_data)} JSON files to:\n{output_folder}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save files: {e}")

    def export_txt(self):
        if not self.json_data: return
        txt_path = filedialog.asksaveasfilename(title="Export as Text", defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if not txt_path: return

        remove_hyphens = self.remove_hyphens_var.get()
        skip_top = self.skip_top_var.get()
        skip_bottom = self.skip_bottom_var.get()

        try:
            with open(txt_path, 'w', encoding='utf-8') as f:
                for item in self.json_data:
                    res_node = self.extract_res(item["data"])
                    target_texts = res_node.get('gemini_rec_texts', res_node.get('rec_texts', []))
                    
                    lines_to_export = [line for line in target_texts if line.strip()]
                    if not lines_to_export: continue 
                    
                    if skip_bottom > 0: lines_to_export = lines_to_export[skip_top : -skip_bottom]
                    else: lines_to_export = lines_to_export[skip_top :]
                    
                    page_has_text = False
                    for line in lines_to_export:
                        stripped = line.strip()
                        if remove_hyphens and re.search(r'[-‐‑—–]+\s*$', stripped):
                            cleaned = re.sub(r'[-‐‑—–]+\s*$', '', stripped)
                            f.write(cleaned) 
                        else:
                            f.write(stripped + "\n")
                        page_has_text = True
                    
                    if page_has_text:
                        f.write("\n")
                        
            messagebox.showinfo("Success", f"TXT exported successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export TXT: {e}")

    def export_diff_html(self):
        if not self.json_data: return
        html_path = filedialog.asksaveasfilename(title="Export Diff Report", defaultextension=".html", filetypes=[("HTML files", "*.html")])
        if not html_path: return

        html_content = """
        <html><head><meta charset='utf-8'><title>OCR Collaborative Diff Report</title>
        <style>
            body { font-family: Arial, sans-serif; background: #f4f4f9; padding: 20px; }
            h1 { text-align: center; color: #333; }
            .page { background: white; padding: 15px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .diff-table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { padding: 8px; border: 1px solid #ddd; text-align: left; vertical-align: top; }
            th { background-color: #f8f8f8; width: 50%; }
            .add { background-color: #e6ffed; color: #22863a; font-weight: bold;}
            .del { background-color: #ffeef0; color: #cb2431; text-decoration: line-through;}
        </style>
        </head><body>
        <h1>OCR Review Diff Report</h1>
        """

        changes_found = False
        for idx, item in enumerate(self.json_data):
            res_node = self.extract_res(item["data"])
            page_num = res_node.get("page_index")
            if page_num is None: page_num = idx
            page_num += 1
            
            status = res_node.get("page_status", "🔴 Not Started")
            orig_texts = res_node.get('original_texts', [])
            edit_texts = res_node.get('gemini_rec_texts', res_node.get('rec_texts', []))
            
            if orig_texts == edit_texts: continue

            changes_found = True
            html_content += f"<div class='page'><h3>Page {page_num} - {status}</h3>"
            html_content += "<table class='diff-table'><tr><th>Original OCR/AI</th><th>Human Edit</th></tr>"

            max_len = max(len(orig_texts), len(edit_texts))
            for i in range(max_len):
                orig_line = orig_texts[i] if i < len(orig_texts) else ""
                edit_line = edit_texts[i] if i < len(edit_texts) else ""
                if orig_line == edit_line: continue 

                matcher = difflib.SequenceMatcher(None, orig_line, edit_line)
                orig_html, edit_html = "", ""

                for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                    if tag == 'equal':
                        orig_html += orig_line[i1:i2]
                        edit_html += edit_line[j1:j2]
                    elif tag == 'delete':
                        orig_html += f"<span class='del'>{orig_line[i1:i2]}</span>"
                    elif tag == 'insert':
                        edit_html += f"<span class='add'>{edit_line[j1:j2]}</span>"
                    elif tag == 'replace':
                        orig_html += f"<span class='del'>{orig_line[i1:i2]}</span>"
                        edit_html += f"<span class='add'>{edit_line[j1:j2]}</span>"

                html_content += f"<tr><td>{orig_html}</td><td>{edit_html}</td></tr>"
            
            html_content += "</table></div>"

        if not changes_found: html_content += "<p style='text-align:center;'>No edits found in the entire book.</p>"
        html_content += "</body></html>"

        try:
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            messagebox.showinfo("Success", f"HTML Diff Report generated successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export HTML: {e}")

    def prev_page(self):
        if self.current_page_idx > 0:
            self.silent_auto_save()
            self.current_page_idx -= 1
            self.current_line_idx = self.get_smart_start_line()
            self.refresh_view()

    def next_page(self):
        if self.json_data and self.current_page_idx < len(self.json_data) - 1:
            self.silent_auto_save()
            self.current_page_idx += 1
            self.current_line_idx = self.get_smart_start_line()
            self.refresh_view()

    def refresh_view(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        self.canvas.yview_moveto(0)

        if not self.json_data: return

        total_pages = len(self.json_data)
        self.page_label.config(text=f"Page: {self.current_page_idx + 1}/{total_pages}")

        res_node = self.get_res_node(self.current_page_idx)
        self.status_var.set(res_node.get("page_status", "🔴 Not Started"))

        img_path = None
        if self.image_paths and self.current_page_idx < len(self.image_paths):
            img_path = self.image_paths[self.current_page_idx]

        rec_polys = res_node.get('rec_polys', [])
        target_texts = res_node.get('gemini_rec_texts', res_node.get('rec_texts', []))
        orig_texts = res_node.get('original_texts', [])
        
        if not target_texts:
            tk.Label(self.scrollable_frame, text="📄 Blank Page (No text detected)", font=("Arial", 18, "bold"), fg="gray").pack(pady=40)
            if self.edit_mode_var.get() == "Full Page" and img_path:
                self.create_full_page_widget(self.scrollable_frame, res_node, img_path)
            return

        reviewed_lines = res_node.get('reviewed_lines', [])
        while len(reviewed_lines) < len(target_texts): reviewed_lines.append(False)
        if len(reviewed_lines) > len(target_texts): reviewed_lines = reviewed_lines[:len(target_texts)]
        res_node['reviewed_lines'] = reviewed_lines

        self.active_text_widget = None
        self.line_widgets.clear()
        
        current_mode = self.edit_mode_var.get()

        if current_mode == "Full Page":
            self.create_full_page_widget(self.scrollable_frame, res_node, img_path)
            
        elif current_mode == "Speed Mode":
            if self.current_line_idx >= len(target_texts): self.current_line_idx = 0 
            if len(target_texts) > 0:
                poly = rec_polys[self.current_line_idx] if self.current_line_idx < len(rec_polys) else []
                text = target_texts[self.current_line_idx]
                orig_text = orig_texts[self.current_line_idx] if self.current_line_idx < len(orig_texts) else ""
                
                self.create_line_widget(self.scrollable_frame, res_node, self.current_line_idx, poly, text, orig_text, img_path)
                info_text = f"Line {self.current_line_idx + 1} of {len(target_texts)}\n[Enter] = Confirm & Next  |  [Shift+Enter] = Prev Line"
                tk.Label(self.scrollable_frame, text=info_text, fg="gray", bg="#e8e8e8", font=("Arial", 10)).pack(pady=15)
                
        elif current_mode == "Low Conf":
            lc_indices = res_node.get('low_conf_indices', {})
            
            if not lc_indices:
                tk.Label(self.scrollable_frame, text="✅ No Low Confidence lines on this page.", font=("Arial", 14, "bold"), fg="green").pack(pady=40)
            else:
                if self.current_line_idx not in lc_indices:
                    self.current_line_idx = self.get_smart_start_line()
                    if self.current_line_idx == 0 and 0 not in lc_indices:
                        self.current_line_idx = sorted(lc_indices.keys())[0]

                poly = rec_polys[self.current_line_idx] if self.current_line_idx < len(rec_polys) else []
                text = target_texts[self.current_line_idx]
                orig_text = orig_texts[self.current_line_idx] if self.current_line_idx < len(orig_texts) else ""
                
                self.create_line_widget(self.scrollable_frame, res_node, self.current_line_idx, poly, text, orig_text, img_path)
                info_text = f"Reviewing Low Confidence {self.current_line_idx + 1} of {len(target_texts)}\n[Enter] = Next  |  [Shift+Enter] = Prev"
                tk.Label(self.scrollable_frame, text=info_text, fg="#b8860b", bg="#e8e8e8", font=("Arial", 10)).pack(pady=15)

        else:
            for idx, text in enumerate(target_texts):
                poly = rec_polys[idx] if idx < len(rec_polys) else []
                orig_text = orig_texts[idx] if idx < len(orig_texts) else ""
                self.create_line_widget(self.scrollable_frame, res_node, idx, poly, text, orig_text, img_path)

        if self.active_text_widget:
            self.root.after(50, self.active_text_widget.focus_set)
            if current_mode == "All Lines" and self.current_line_idx > 0:
                self.root.after(100, lambda: self.scroll_to_widget(self.active_text_widget))

    def create_full_page_widget(self, parent, res_node, img_path):
        frame = tk.Frame(parent, bd=2, relief=tk.RIDGE, pady=10, padx=10, bg="white")
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        is_side_by_side = self.side_by_side_var.get()
        zoom_val = max(0.1, self.ui_zoom_var.get())

        if img_path and os.path.exists(img_path):
            try:
                full_img = Image.open(img_path)
                fp_zoom = min(zoom_val, 1.5) 
                
                new_w = int(full_img.width * fp_zoom)
                new_h = int(full_img.height * fp_zoom)
                if new_w > 0 and new_h > 0:
                    img = full_img.resize((new_w, new_h), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    img_label = tk.Label(frame, image=photo, bg='gray')
                    img_label.image = photo 
                    
                    if is_side_by_side: img_label.pack(side=tk.LEFT, padx=(0, 15), anchor=tk.N)
                    else: img_label.pack(side=tk.TOP, pady=(0, 10), anchor=tk.CENTER)
            except Exception: pass

        text_container = tk.Frame(frame, bg="white")
        if is_side_by_side: text_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        else: text_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        target_texts = res_node.get('gemini_rec_texts', res_node.get('rec_texts', []))
        orig_texts = res_node.get('original_texts', [])
        reviewed_lines = res_node.get('reviewed_lines', [])
        lc_indices = res_node.get('low_conf_indices', {})
        text_array_key = 'gemini_rec_texts' if 'gemini_rec_texts' in res_node else 'rec_texts'
        
        custom_font = ("Arial", max(6, self.font_size_var.get()))

        for idx, text in enumerate(target_texts):
            orig_t = orig_texts[idx] if idx < len(orig_texts) else ""
            is_reviewed = reviewed_lines[idx]
            is_lc = idx in lc_indices
            
            if is_reviewed: bg_color = "#e6ffed" 
            elif is_lc: bg_color = "#fff3cd" 
            else: bg_color = "white"
            
            box_frame = tk.Frame(text_container, bg="white")
            
            if is_side_by_side:
                box_frame.pack(side=tk.LEFT, fill=tk.Y, padx=2)
                
                if is_lc:
                    tk.Label(box_frame, text="⚠️\n"+"\n".join(list(lc_indices[idx])), fg="#b8860b", font=("Arial", 8), bg="white").pack(side=tk.TOP)

                diff_label = tk.Label(box_frame, text="", fg="gray", font=("Arial", max(8, self.font_size_var.get()-4)), bg="#f9f9f9")
                diff_label.pack(side=tk.LEFT, fill=tk.Y)
                
                text_widget = tk.Text(box_frame, width=2, height=max(5, len(text)), font=custom_font, wrap=tk.CHAR, bg=bg_color, undo=True)
                text_widget.insert("1.0", text)
                text_widget.edit_modified(False) 
                text_widget.pack(side=tk.LEFT, fill=tk.Y)
                
                self.line_widgets.append(text_widget)

                def make_on_modified(w, l, o_txt, i):
                    def handler(event):
                        if w.edit_modified():
                            val = w.get("1.0", "end-1c").replace('\n', '')
                            res_node[text_array_key][i] = val
                            self.mark_line_reviewed(i)
                            w.config(bg="#e6ffed") 
                            
                            if val != o_txt: l.config(text="\n".join(list(o_txt)))
                            else: l.config(text="")
                            w.edit_modified(False)
                    return handler

                text_widget.bind("<<Modified>>", make_on_modified(text_widget, diff_label, orig_t, idx))
                text_widget.bind("<FocusIn>", lambda e, i=idx: self.set_active_line(i))
                
                if text != orig_t: diff_label.config(text="\n".join(list(orig_t)))
                if idx == self.current_line_idx: self.active_text_widget = text_widget
            else:
                box_frame.pack(side=tk.TOP, fill=tk.X, pady=2)
                
                if is_lc:
                    tk.Label(box_frame, text=f"⚠️ Low Confidence: {lc_indices[idx]}", fg="#b8860b", font=("Arial", 9, "bold"), bg="white", anchor="w").pack(side=tk.TOP, fill=tk.X)
                    
                text_var = tk.StringVar(value=text)
                entry = tk.Entry(box_frame, textvariable=text_var, width=60, font=custom_font, bg=bg_color)
                entry.pack(side=tk.TOP, fill=tk.X)
                
                self.line_widgets.append(entry)
                
                diff_label = tk.Label(box_frame, text="", fg="gray", font=("Arial", max(8, self.font_size_var.get()-4)), bg="#f9f9f9", anchor="w")
                diff_label.pack(side=tk.TOP, fill=tk.X)

                def make_on_change(var, l, e_widget, o_txt, i):
                    def handler(*args):
                        val = var.get()
                        res_node[text_array_key][i] = val
                        self.mark_line_reviewed(i)
                        e_widget.config(bg="#e6ffed") 
                        
                        if val != o_txt: l.config(text=f"Orig: {o_txt}")
                        else: l.config(text="")
                    return handler
                
                text_var.trace_add("write", make_on_change(text_var, diff_label, entry, orig_t, idx))
                entry.bind("<FocusIn>", lambda e, i=idx: self.set_active_line(i))
                
                if text != orig_t: diff_label.config(text=f"Orig: {orig_t}")
                if idx == self.current_line_idx: self.active_text_widget = entry

    def create_line_widget(self, parent, res_node, index, poly, text, orig_text, img_path):
        frame = tk.Frame(parent, bd=2, relief=tk.RIDGE, pady=10, padx=10, bg="white")
        frame.pack(fill=tk.X, padx=20, pady=10)

        center_wrapper = tk.Frame(frame, bg="white")
        center_wrapper.pack(expand=True, anchor=tk.CENTER)

        is_side_by_side = self.side_by_side_var.get()
        zoom_val = max(0.1, self.ui_zoom_var.get())
        custom_font = ("Arial", max(6, self.font_size_var.get()))
        text_array_key = 'gemini_rec_texts' if 'gemini_rec_texts' in res_node else 'rec_texts'

        is_reviewed = res_node.get('reviewed_lines', [])[index]
        lc_indices = res_node.get('low_conf_indices', {})
        is_lc = index in lc_indices

        if is_reviewed: bg_color = "#e6ffed"
        elif is_lc: bg_color = "#fff3cd"
        else: bg_color = "white"

        if img_path and os.path.exists(img_path) and len(poly) == 4:
            try:
                pad = self.padding_var.get()
                coord_scale = max(0.01, self.scale_var.get())
                
                img_poly = [(p[0] / coord_scale, p[1] / coord_scale) for p in poly]
                
                xs = [p[0] for p in img_poly]
                ys = [p[1] for p in img_poly]
                img_xmin, img_xmax = min(xs), max(xs)
                img_ymin, img_ymax = min(ys), max(ys)
                
                full_img = Image.open(img_path)
                
                # Simply extract the mathematical furthest bounds of the raw polygon
                crop_box = (
                    max(0, img_xmin - pad),
                    max(0, img_ymin - pad),
                    min(full_img.width, img_xmax + pad),
                    min(full_img.height, img_ymax + pad)
                )
                
                final_img = full_img.crop(crop_box)

                new_w = int(final_img.width * zoom_val)
                new_h = int(final_img.height * zoom_val)
                if new_w > 0 and new_h > 0:
                    final_img = final_img.resize((new_w, new_h), Image.LANCZOS)
                
                photo = ImageTk.PhotoImage(final_img)
                img_label = tk.Label(center_wrapper, image=photo, bg='gray')
                img_label.image = photo 
                
                if is_side_by_side: img_label.pack(side=tk.LEFT, padx=(0, 15), anchor=tk.N)
                else: img_label.pack(side=tk.TOP, pady=(0, 5), anchor=tk.CENTER)
            except Exception as e:
                tk.Label(center_wrapper, text=f"Render Error: {e}", fg="red", bg="white").pack(side=tk.TOP)

        if is_lc:
            tk.Label(center_wrapper, text=f"⚠️ {lc_indices[index]}", fg="#b8860b", font=("Arial", 9, "bold"), bg="white").pack(side=tk.TOP, fill=tk.X)

        if is_side_by_side:
            diff_label = tk.Label(center_wrapper, text="", fg="gray", font=("Arial", max(8, self.font_size_var.get()-4)), bg="#f9f9f9")
            diff_label.pack(side=tk.LEFT, fill=tk.Y)
            
            text_widget = tk.Text(center_wrapper, width=2, height=max(5, len(text)), font=custom_font, wrap=tk.CHAR, bg=bg_color, undo=True)
            text_widget.insert("1.0", text)
            text_widget.edit_modified(False)
            text_widget.pack(side=tk.LEFT, fill=tk.Y, pady=5)
            
            self.line_widgets.append(text_widget)

            text_widget.bind("<FocusIn>", lambda e, i=index: self.set_active_line(i))
            text_widget.bind("<Return>", self.advance_line)
            text_widget.bind("<Shift-Return>", self.previous_line)

            def on_text_modified(event):
                if text_widget.edit_modified():
                    val = text_widget.get("1.0", "end-1c").replace('\n', '')
                    res_node[text_array_key][index] = val
                    self.mark_line_reviewed(index)
                    text_widget.config(bg="#e6ffed") 
                    
                    if val != orig_text: diff_label.config(text="\n".join(list(orig_text)))
                    else: diff_label.config(text="")
                    text_widget.edit_modified(False)
                    
            text_widget.bind("<<Modified>>", on_text_modified)
            if index == self.current_line_idx: self.active_text_widget = text_widget 
            if text != orig_text: diff_label.config(text="\n".join(list(orig_text)))

        else:
            text_var = tk.StringVar(value=text)
            entry = tk.Entry(center_wrapper, textvariable=text_var, width=80, font=custom_font, justify="center", bg=bg_color)
            entry.pack(side=tk.TOP, ipady=4, pady=(5, 0))
            
            self.line_widgets.append(entry)
            
            diff_label = tk.Label(center_wrapper, text="", fg="gray", font=("Arial", max(8, self.font_size_var.get()-4)), bg="#f9f9f9")
            diff_label.pack(side=tk.TOP, fill=tk.X)

            entry.bind("<FocusIn>", lambda e, i=index: self.set_active_line(i))
            entry.bind("<Return>", self.advance_line)
            entry.bind("<Shift-Return>", self.previous_line)

            def on_change(*args):
                val = text_var.get()
                res_node[text_array_key][index] = val
                self.mark_line_reviewed(index)
                entry.config(bg="#e6ffed") 
                
                if val != orig_text: diff_label.config(text=f"Orig: {orig_text}")
                else: diff_label.config(text="")
                    
            text_var.trace_add("write", on_change)
            if index == self.current_line_idx: self.active_text_widget = entry
            if text != orig_text: diff_label.config(text=f"Orig: {orig_text}")

if __name__ == "__main__":
    root = tk.Tk()
    app = OCREditorApp(root)
    root.mainloop()