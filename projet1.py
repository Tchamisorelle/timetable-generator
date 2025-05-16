from ortools.sat.python import cp_model
import json
import time
import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

class TimeTableGenerator:
    def __init__(self, subjects_file, rooms_file):
        """Initialise le générateur d'emploi du temps avec les fichiers de données."""
        # Chargement des données
        with open(subjects_file, 'r', encoding='utf-8') as f:
            self.subjects_data = json.load(f)
        
        with open(rooms_file, 'r', encoding='utf-8') as f:
            self.rooms_data = json.load(f)
        
        # Initialisation des données
        self.L = []  # Classes (L pour Level-semester)
        self.C = []  # Cours
        self.R = []  # Salles
        self.T = []  # Enseignants
        self.D = list(range(1, 7))  # 6 jours
        self.P = list(range(1, 6))  # 5 périodes
        
        # Poids pour l'optimisation (poids plus élevés pour les matinées)
        self.weights = {1: 5, 2: 4, 3: 3, 4: 2, 5: 1}
        
        # Relation cours-classe (programme)
        self.programme = {}  # (l, c) -> booléen
        
        # Relation cours-enseignant
        self.course_teachers = {}  # (c, t) -> booléen
        
        # Crédits des cours (pour priorisation)
        self.course_credits = {}  # c -> valeur
        
        # Extraction des données
        self.extract_data()

    def clean_string(self, s):
        """Nettoie une chaîne de caractères."""
        if isinstance(s, str):
            return s.strip()
        return ""

    def extract_data(self):
        """Extrait toutes les données nécessaires des fichiers JSON."""
        # Enseignant par défaut pour les cours sans enseignant
        default_teacher = "ENSEIGNANT_DEFAUT"
        
        # 1. Extraction des classes, cours et enseignants
        for level, level_data in self.subjects_data['niveau'].items():
            for semester, semester_data in level_data.items():
                class_name = f"Niveau {level}-{semester}"
                self.L.append(class_name)
                self.programme[class_name] = []
                
                for subject in semester_data['subjects']:
                    course_code = self.clean_string(subject['code'])
                    if not course_code:
                        continue
                    
                    if course_code not in self.C:
                        self.C.append(course_code)
                        self.course_teachers[course_code] = []
                        try:
                            self.course_credits[course_code] = int(subject.get('credit', 0))
                        except:
                            self.course_credits[course_code] = 0
                    
                    self.programme[class_name].append(course_code)
                    
                    # Extraction des enseignants
                    teachers_found = False
                    
                    # Lecture des enseignants principaux
                    if 'Course Lecturer' in subject:
                        for lecturer in subject['Course Lecturer']:
                            lecturer = self.clean_string(lecturer)
                            if lecturer:
                                if lecturer not in self.T:
                                    self.T.append(lecturer)
                                if lecturer not in self.course_teachers[course_code]:
                                    self.course_teachers[course_code].append(lecturer)
                                teachers_found = True
                    
                    # Lecture des assistants
                    if 'Assitant lecturer' in subject:
                        for lecturer in subject['Assitant lecturer']:
                            lecturer = self.clean_string(lecturer)
                            if lecturer:
                                if lecturer not in self.T:
                                    self.T.append(lecturer)
                                if lecturer not in self.course_teachers[course_code]:
                                    self.course_teachers[course_code].append(lecturer)
                                teachers_found = True
                    
                    # Ajout d'un enseignant par défaut si nécessaire
                    if not teachers_found:
                        if default_teacher not in self.T:
                            self.T.append(default_teacher)
                        self.course_teachers[course_code].append(default_teacher)
        
        # 2. Extraction des salles
        for room in self.rooms_data['Informatique']:
            room_num = self.clean_string(room['num'])
            if room_num:
                self.R.append(room_num)
        
        print(f"Données extraites: {len(self.L)} classes, {len(self.C)} cours, {len(self.R)} salles, {len(self.T)} enseignants")
        print(f"Total de cours à programmer: {sum(len(courses) for courses in self.programme.values())}")
        print(f"Total de créneaux disponibles: {len(self.D) * len(self.P)}")

    def generate_timetable(self):
        """Génère l'emploi du temps avec une approche relâchée permettant une solution partielle."""
        print("\nTentative avec approche relâchée (solution partielle)...")
        
        # Création du modèle
        model = cp_model.CpModel()
        
        # 1. VARIABLES DE DÉCISION
        # x[l,c,r,d,p,t] = 1 si la classe l suit le cours c dans la salle r pendant 
        # la période p du jour d avec l'enseignant t, 0 sinon
        x = {}
        
        # Création des variables uniquement pour les combinaisons valides
        for l in self.L:
            for c in self.programme[l]:
                for r in self.R:
                    for d in self.D:
                        for p in self.P:
                            for t in self.course_teachers[c]:
                                x[(l, c, r, d, p, t)] = model.NewBoolVar(f'x_{l}_{c}_{r}_{d}_{p}_{t}')
        
        # Variable y[l,c] = 1 si le cours c de la classe l est programmé, 0 sinon
        y = {}
        for l in self.L:
            for c in self.programme[l]:
                y[(l, c)] = model.NewBoolVar(f'y_{l}_{c}')
                
                # Liaison entre x et y : y[l,c] = 1 ssi le cours est programmé quelque part
                model.Add(y[(l, c)] == sum(x.get((l, c, r, d, p, t), 0)
                                         for r in self.R
                                         for d in self.D
                                         for p in self.P
                                         for t in self.course_teachers[c]))
        
        # 2. CONTRAINTES
        
        # Contrainte 1: Pas de conflits d'horaire pour une classe
        for l in self.L:
            for d in self.D:
                for p in self.P:
                    model.Add(sum(x.get((l, c, r, d, p, t), 0) 
                               for c in self.programme[l]
                               for r in self.R 
                               for t in self.course_teachers[c]) 
                           <= 1)
        
        # Contrainte 2: Chaque cours est programmé au plus une fois (et non exactement une fois)
        for l in self.L:
            for c in self.programme[l]:
                model.Add(sum(x.get((l, c, r, d, p, t), 0)
                           for r in self.R
                           for d in self.D
                           for p in self.P
                           for t in self.course_teachers[c])
                       <= 1)  # <= 1 au lieu de == 1
        
        # Contrainte 3: Un enseignant ne peut pas donner deux cours simultanément
        for t in self.T:
            for d in self.D:
                for p in self.P:
                    model.Add(sum(x.get((l, c, r, d, p, t), 0)
                               for l in self.L
                               for c in self.programme[l] if t in self.course_teachers[c]
                               for r in self.R)
                           <= 1)
        
        # Contrainte 4: Une salle ne peut pas accueillir deux cours au même moment
        for r in self.R:
            for d in self.D:
                for p in self.P:
                    model.Add(sum(x.get((l, c, r, d, p, t), 0)
                               for l in self.L
                               for c in self.programme[l]
                               for t in self.course_teachers[c])
                           <= 1)
        
        # 3. FONCTION OBJECTIF: Maximiser le nombre de cours programmés ET les cours du matin
        objective_terms = []
        
        # Grand poids pour chaque cours programmé (priorité 1)
        for l in self.L:
            for c in self.programme[l]:
                # Bonus pour le nombre de crédits
                credit_bonus = self.course_credits.get(c, 0)
                objective_terms.append(1000 * y[(l, c)] + credit_bonus * y[(l, c)])
        
        # Bonus pour les créneaux du matin (priorité 2)
        for l in self.L:
            for c in self.programme[l]:
                for r in self.R:
                    for d in self.D:
                        for p in self.P:
                            for t in self.course_teachers[c]:
                                if (l, c, r, d, p, t) in x:
                                    objective_terms.append(self.weights[p] * x[(l, c, r, d, p, t)])
        
        model.Maximize(sum(objective_terms))
        
        # 4. RÉSOLUTION
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 600  # 10 minutes
        
        print("\nRésolution du modèle en cours...")
        start_time = time.time()
        status = solver.Solve(model)
        end_time = time.time()
        
        print(f"Résolution terminée en {end_time - start_time:.2f} secondes")
        print(f"Statut: {solver.StatusName(status)}")
        
        # 5. TRAITEMENT DES RÉSULTATS
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            print("Solution partielle trouvée!")
            
            # Structure de données pour l'emploi du temps
            timetable = {}
            for l in self.L:
                timetable[l] = {}
                for d in self.D:
                    timetable[l][d] = {}
                    for p in self.P:
                        timetable[l][d][p] = None
            
            # Remplir l'emploi du temps
            for l in self.L:
                for c in self.programme[l]:
                    for r in self.R:
                        for d in self.D:
                            for p in self.P:
                                for t in self.course_teachers[c]:
                                    if (l, c, r, d, p, t) in x and solver.Value(x[(l, c, r, d, p, t)]) == 1:
                                        timetable[l][d][p] = (c, t, r)
            
            # Afficher l'emploi du temps
            self.display_timetable(timetable)
            
            # Générer le PDF élégant
            self.generate_pdf(timetable)
            
            # Calculer et afficher les cours non programmés
            scheduled_courses = set()
            for l in self.L:
                for d in self.D:
                    for p in self.P:
                        if timetable[l][d][p]:
                            c = timetable[l][d][p][0]
                            scheduled_courses.add((l, c))
            
            all_courses = set()
            for l in self.L:
                for c in self.programme[l]:
                    all_courses.add((l, c))
            
            unscheduled = all_courses - scheduled_courses
            if unscheduled:
                print(f"\nCours non programmés: {len(unscheduled)} sur {len(all_courses)}")
                for l, c in sorted(unscheduled):
                    credit = self.course_credits.get(c, 0)
                    print(f"  - {c} (Classe {l}, {credit} crédits)")
            
            return timetable
        else:
            print("Aucune solution trouvée, même avec l'approche relâchée.")
            
            # Analyse des problèmes potentiels
            self.analyze_problem()
            
            return None
    
    def analyze_problem(self):
        """Analyse les problèmes potentiels dans les données."""
        print("\n=== ANALYSE DES PROBLÈMES POTENTIELS ===")
        
        # 1. Vérification des cours sans enseignant
        courses_without_teacher = [c for c in self.C if not self.course_teachers[c]]
        if courses_without_teacher:
            print(f"Cours sans enseignant: {len(courses_without_teacher)}")
            for c in courses_without_teacher:
                print(f"  - {c}")
        
        # 2. Vérification de la distribution des cours par classe
        print("\nDistribution des cours par classe:")
        for l in self.L:
            print(f"  - {l}: {len(self.programme[l])} cours")
        
        # 3. Suggestion d'assouplissement plus radical
        total_courses = sum(len(courses) for courses in self.programme.values())
        total_slots = len(self.D) * len(self.P) * len(self.R)
        
        if total_courses > total_slots:
            print(f"\nProblème fondamental: {total_courses} cours à programmer mais seulement {total_slots} créneaux-salles disponibles.")
            print("Suggestions:")
            print("  1. Augmenter le nombre de salles")
            print("  2. Augmenter le nombre de créneaux (jours ou périodes)")
            print("  3. Réduire le nombre de cours à programmer")
            print("  4. Permettre le partage de salles pour certains cours")
        
        # 4. Vérification de l'unicité des cours
        unique_courses = set(self.C)
        if len(unique_courses) != len(self.C):
            print("\nAttention: Certains codes de cours sont dupliqués!")
    
    def display_timetable(self, timetable):
        """Affiche l'emploi du temps généré."""
        day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
        period_names = [
            "7h00-9h55", 
            "10h05-12h55", 
            "13h05-15h55", 
            "16h05-18h55", 
            "19h05-21h55"
        ]
        
        for l in self.L:
            print(f"\n\n=== EMPLOI DU TEMPS - {l} ===\n")
            for d in self.D:
                print(f"  {day_names[d-1]}:")
                for p in self.P:
                    if timetable[l][d][p]:
                        c, t, r = timetable[l][d][p]
                        print(f"    {period_names[p-1]}: {c} avec {t} dans {r}")
                    else:
                        print(f"    {period_names[p-1]}: -")
        
        # Statistiques
        morning_courses = 0
        total_scheduled = 0
        
        for l in self.L:
            for d in self.D:
                for p in self.P:
                    if timetable[l][d][p]:
                        total_scheduled += 1
                        if p <= 2:  # Période du matin (p1 ou p2)
                            morning_courses += 1
        
        print(f"\nStatistiques:")
        print(f"Total des cours programmés: {total_scheduled}")
        if total_scheduled > 0:
            print(f"Cours programmés le matin: {morning_courses} ({morning_courses*100/total_scheduled:.1f}%)")
    
    def generate_pdf(self, timetable):
        """Génère un PDF élégant de l'emploi du temps (seulement les tables)."""
        print("\nGénération du PDF de l'emploi du temps...")
        
        # Créer le dossier de sortie s'il n'existe pas
        output_dir = "output"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # Définir les dimensions du document
        doc = SimpleDocTemplate("emploi_du_temps.pdf", 
                              pagesize=landscape(A4), 
                              rightMargin=1*cm, leftMargin=1*cm,
                              topMargin=1*cm, bottomMargin=1*cm)
        
        # Définir les styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            name='TitleStyle',
            parent=styles['Title'],
            fontSize=24,
            leading=30,
            alignment=1,  # Centre
            spaceAfter=0.5*cm
        )
        heading_style = ParagraphStyle(
            name='HeadingStyle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.blue,
            spaceAfter=0.3*cm
        )
        normal_style = styles['Normal']
        
        # Couleurs pour les périodes
        period_colors = {
            1: colors.Color(0.8, 1, 0.8),  # Vert clair pour le matin tôt
            2: colors.Color(0.9, 1, 0.9),  # Vert très clair pour le matin
            3: colors.Color(1, 1, 0.8),    # Jaune clair pour le midi
            4: colors.Color(1, 0.9, 0.8),  # Orange clair pour l'après-midi
            5: colors.Color(1, 0.8, 0.8)   # Rouge clair pour le soir
        }
        
        # Liste des éléments à ajouter au document
        elements = []
        
        # Titre du document
        elements.append(Paragraph("Emploi du Temps", title_style))
        elements.append(Paragraph("Département d'Informatique - Université de Yaoundé I", heading_style))
        elements.append(Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}", normal_style))
        elements.append(Spacer(1, 0.5*cm))
        
        # Définir les noms des jours et périodes
        day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
        period_names = [
            "7h00-9h55", 
            "10h05-12h55", 
            "13h05-15h55", 
            "16h05-18h55", 
            "19h05-21h55"
        ]
        
        # Pour chaque classe, créer une section d'emploi du temps
        for l in self.L:
            elements.append(PageBreak())
            elements.append(Paragraph(f"Emploi du Temps - {l}", heading_style))
            elements.append(Spacer(1, 0.3*cm))
            
            # Créer un tableau pour l'emploi du temps
            data = [["Période"] + day_names]
            
            for p in self.P:
                row = [period_names[p-1]]
                for d in self.D:
                    if timetable[l][d][p]:
                        c, t, r = timetable[l][d][p]
                        cell_text = f"{c}\nProf: {self.truncate_text(t)}\nSalle: {r}"
                        row.append(cell_text)
                    else:
                        row.append("")
                data.append(row)
            
            col_widths = [3*cm] + [4*cm] * len(day_names)
            table = Table(data, colWidths=col_widths, rowHeights=[1*cm] + [2.5*cm] * len(self.P))
            
            # Style du tableau
            table_style = TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('WORDWRAP', (0, 0), (-1, -1), True),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
            ])
            
            # Ajouter des couleurs selon les périodes
            for p in self.P:
                for d_idx in range(len(day_names)):
                    table_style.add('BACKGROUND', (d_idx+1, p), (d_idx+1, p), period_colors[p])
            
            table.setStyle(table_style)
            elements.append(table)
        
        # Générer le PDF
        doc.build(elements)
        print(f"PDF généré avec succès: emploi_du_temps.pdf")

    def truncate_text(self, text, max_length=15):
        """Tronque un texte s'il est trop long."""
        if len(text) <= max_length:
            return text
        return text[:max_length-3] + '...'

def main():
    # Instancier et exécuter le générateur d'emploi du temps
    generator = TimeTableGenerator('subjects.json', 'rooms.json')
    timetable = generator.generate_timetable()
    
    if timetable:
        print("Emploi du temps généré avec succès!")

if __name__ == "__main__":
    main()