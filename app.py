import os
import numpy as np
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from werkzeug.utils import secure_filename
import tensorflow as tf
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
import cv2
import traceback
import logging
import sqlite3
from datetime import datetime
import io
import csv
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'brain_tumor_detection_key'

# Configuration
UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload size
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
DATABASE = 'brain_tumor_detection.db'

# Ensure the upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Class names
class_names = ['Glioma Tumor', 'Meningioma Tumor', 'No Tumor', 'Pituitary Tumor']

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_tumor_model():
    """Load the trained model with error handling"""
    model_path = 'resnet_model.h5'
    try:
        if os.path.exists(model_path):
            model = load_model(model_path)
            logger.info("Model loaded successfully")
            return model
        else:
            logger.error(f"Model file not found at {model_path}")
            return None
    except Exception as e:
        logger.error(f"Error loading model: {str(e)}")
        logger.error(traceback.format_exc())
        return None

# Load the model
model = load_tumor_model()

# Initialize database
def init_db():
    """Initialize the SQLite database with tables if they don't exist"""
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        # Create scans table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            prediction TEXT NOT NULL,
            confidence REAL NOT NULL,
            date TEXT NOT NULL
        )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {str(e)}")

# Save scan to database
def save_scan(filename, prediction, confidence):
    """Save scan details to the database"""
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        date = datetime.now().strftime('%Y-%m-%d')
        cursor.execute(
            "INSERT INTO scans (filename, prediction, confidence, date) VALUES (?, ?, ?, ?)",
            (filename, prediction, confidence, date)
        )
        
        scan_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Scan saved to database with ID: {scan_id}")
        return scan_id
    except Exception as e:
        logger.error(f"Error saving scan to database: {str(e)}")
        return None

# Get scan by filename
def get_scan_by_filename(filename):
    """Get scan details from the database by filename"""
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM scans WHERE filename = ? ORDER BY id DESC LIMIT 1", (filename,))
        scan = cursor.fetchone()
        
        conn.close()
        
        if scan:
            return dict(scan)
        else:
            return None
    except Exception as e:
        logger.error(f"Error retrieving scan: {str(e)}")
        return None

# Get recent scans
def get_recent_scans(limit=5):
    """Get the most recent scans from the database"""
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,))
        recent_scans = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return recent_scans
    except Exception as e:
        logger.error(f"Error retrieving recent scans: {str(e)}")
        return []

# Get all scans for export
def get_all_scans():
    """Get all scans from the database for export"""
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM scans ORDER BY id DESC")
        scans = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return scans
    except Exception as e:
        logger.error(f"Error retrieving all scans: {str(e)}")
        return []

# Get scan statistics
def get_scan_statistics():
    """Get statistics about the scans for the dashboard"""
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        # Total scans
        cursor.execute("SELECT COUNT(*) FROM scans")
        total_scans = cursor.fetchone()[0]
        
        # Count by tumor type
        cursor.execute("SELECT COUNT(*) FROM scans WHERE prediction = 'No Tumor'")
        no_tumor = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM scans WHERE prediction = 'Glioma Tumor'")
        glioma = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM scans WHERE prediction = 'Meningioma Tumor'")
        meningioma = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM scans WHERE prediction = 'Pituitary Tumor'")
        pituitary = cursor.fetchone()[0]
        
        # Monthly scans (last 6 months)
        # This is simplified and would need to be adjusted for actual month counts
        monthly_scans = []
        current_month = datetime.now().month
        current_year = datetime.now().year
        
        for i in range(6):
            month = (current_month - i) % 12
            if month == 0:
                month = 12
            year = current_year if month <= current_month else current_year - 1
            
            # Format the month for SQL query
            month_str = f"{year}-{month:02d}-%"
            
            cursor.execute("SELECT COUNT(*) FROM scans WHERE date LIKE ?", (month_str,))
            count = cursor.fetchone()[0]
            monthly_scans.append(count)
        
        monthly_scans.reverse()  # Reverse to get chronological order
        
        conn.close()
        
        return {
            'total_scans': total_scans,
            'tumor_detected': total_scans - no_tumor,
            'no_tumor': no_tumor,
            'glioma': glioma,
            'meningioma': meningioma,
            'pituitary': pituitary,
            'monthly_scans': monthly_scans
        }
    except Exception as e:
        logger.error(f"Error retrieving scan statistics: {str(e)}")
        # Return default values if there's an error
        return {
            'total_scans': 0,
            'tumor_detected': 0,
            'no_tumor': 0,
            'glioma': 0,
            'meningioma': 0,
            'pituitary': 0,
            'monthly_scans': [0, 0, 0, 0, 0, 0]
        }

def preprocess_image(img_path):
    """Preprocess image for model prediction"""
    try:
        # Convert to absolute path and normalize to handle Windows backslashes
        img_path = os.path.abspath(os.path.normpath(img_path))
        logger.info(f"Reading image from: {img_path}")
        
        # Try multiple methods to load the image
        img = None
        # Method 1: Using cv2.imread directly
        img = cv2.imread(img_path)
        
        # Method 2: If that fails, try with np.fromfile
        if img is None:
            try:
                with open(img_path, 'rb') as file:
                    img_array = np.frombuffer(file.read(), dtype=np.uint8)
                    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            except Exception as e:
                logger.error(f"Error reading with np.frombuffer: {str(e)}")
        
        if img is None:
            logger.error(f"Failed to load image from {img_path}")
            return None
            
        img = cv2.resize(img, (150, 150))
        img = img / 255.0  # Normalize
        img = np.expand_dims(img, axis=0)  # Add batch dimension
        return img
    except Exception as e:
        logger.error(f"Error preprocessing image: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def generate_pdf_report(scan_data, image_path):
    """Generate a PDF report for a brain tumor detection scan"""
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []
        
        # Custom styles
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.darkblue,
            spaceAfter=12
        )
        
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.darkblue,
            spaceAfter=8
        )
        
        normal_style = styles['Normal']
        
        # Add title
        elements.append(Paragraph("Brain Tumor Detection Report", title_style))
        elements.append(Spacer(1, 0.2*inch))
        
        # Add date and time
        elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", normal_style))
        elements.append(Spacer(1, 0.2*inch))
        
        # Add scan details
        elements.append(Paragraph("Scan Details", subtitle_style))
        scan_details = [
            ["ID", str(scan_data['id'])],
            ["Date", scan_data['date']],
            ["Filename", scan_data['filename']]
        ]
        
        details_table = Table(scan_details, colWidths=[1.5*inch, 4*inch])
        details_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.darkblue),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Add MRI image - use a more robust method to load the image
        elements.append(Paragraph("MRI Scan Image", subtitle_style))
        image_added = False
        
        if os.path.exists(image_path):
            try:
                # First try the reportlab Image directly
                img = Image(image_path, width=4*inch, height=4*inch)
                elements.append(img)
                image_added = True
            except Exception as e:
                logger.error(f"Error adding image to PDF with standard method: {str(e)}")
                try:
                    # If that fails, try to load with PIL and convert
                    from PIL import Image as PILImage
                    pil_img = PILImage.open(image_path)
                    img_temp_path = os.path.join(os.path.dirname(image_path), f"temp_{os.path.basename(image_path)}")
                    pil_img.save(img_temp_path)
                    img = Image(img_temp_path, width=4*inch, height=4*inch)
                    elements.append(img)
                    image_added = True
                    try:
                        # Clean up temp file
                        os.remove(img_temp_path)
                    except:
                        pass
                except Exception as e2:
                    logger.error(f"Error adding image to PDF with PIL method: {str(e2)}")
        
        if not image_added:
            elements.append(Paragraph("Image not available or could not be loaded", normal_style))
        
        elements.append(Spacer(1, 0.2*inch))
        
        # Add detection results
        elements.append(Paragraph("Detection Results", subtitle_style))
        
        # Format confidence with 1 decimal place
        confidence = round(scan_data['confidence'], 1)
        
        results = [
            ["Prediction", scan_data['prediction']],
            ["Confidence", f"{confidence}%"]
        ]
        
        # Add color coding based on prediction
        bg_color = colors.lightgreen
        if scan_data['prediction'] != 'No Tumor':
            if 'Glioma' in scan_data['prediction']:
                bg_color = colors.lightblue
            elif 'Meningioma' in scan_data['prediction']:
                bg_color = colors.lightcyan
            else:
                bg_color = colors.lightyellow
                
        results_table = Table(results, colWidths=[1.5*inch, 4*inch])
        results_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('BACKGROUND', (1, 0), (1, 0), bg_color),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.darkblue),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(results_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Add recommendations
        elements.append(Paragraph("Recommendations", subtitle_style))
        if scan_data['prediction'] == 'No Tumor':
            recommendations = [
                "Continue with regular health check-ups as advised by your healthcare provider.",
                "If symptoms persist despite this negative finding, follow up with your healthcare provider.",
                "Maintain a healthy lifestyle to support overall brain health."
            ]
        else:
            recommendations = [
                "Consult with a neurologist or neurosurgeon for a thorough evaluation.",
                "Additional imaging studies (e.g., contrast-enhanced MRI) may be needed for further assessment.",
                "Consider a biopsy for definitive diagnosis if clinically indicated.",
                "Develop a treatment plan based on tumor type, size, location, and patient factors."
            ]
        
        for rec in recommendations:
            elements.append(Paragraph(f"• {rec}", normal_style))
            elements.append(Spacer(1, 0.1*inch))
        
        elements.append(Spacer(1, 0.2*inch))
        
        # Add disclaimer
        disclaimer_style = ParagraphStyle(
            'Disclaimer',
            parent=styles['Italic'],
            fontSize=9,
            textColor=colors.darkgrey
        )
        disclaimer = "Disclaimer: This is an AI-assisted detection and should not replace professional medical diagnosis. Always consult with a healthcare provider for clinical decisions."
        elements.append(Paragraph(disclaimer, disclaimer_style))
        
        # Build the PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def generate_csv_export():
    """Generate a CSV export of all scans"""
    try:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        
        # Write header
        writer.writerow(['ID', 'Date', 'Filename', 'Prediction', 'Confidence (%)'])
        
        # Write scan data
        scans = get_all_scans()
        for scan in scans:
            writer.writerow([
                scan['id'],
                scan['date'],
                scan['filename'],
                scan['prediction'],
                round(scan['confidence'], 1)
            ])
        
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.error(f"Error generating CSV: {str(e)}")
        return None

@app.route('/')
def index():
    """Home page route"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and tumor detection"""
    # Check if model is loaded
    if model is None:
        flash('Model not loaded. Please contact the administrator.')
        return redirect(url_for('index'))
        
    # Check if the post request has the file part
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)
    
    file = request.files['file']
    
    # If user does not select file, browser also
    # submit an empty part without filename
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('index'))
    
    # Check if the file is allowed
    if file and allowed_file(file.filename):
        try:
            # Secure filename and save file
            filename = secure_filename(file.filename)
            # Ensure directory exists
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            
            # Create absolute file path
            file_path = os.path.abspath(os.path.normpath(os.path.join(app.config['UPLOAD_FOLDER'], filename)))
            logger.info(f"Saving uploaded file to: {file_path}")
            
            # Save the file
            file.save(file_path)
            
            # Verify file was saved correctly
            if not os.path.exists(file_path):
                logger.error(f"File was not saved correctly at {file_path}")
                flash('Error saving file. Please try again.')
                return redirect(url_for('index'))
                
            logger.info(f"File saved successfully. Size: {os.path.getsize(file_path)} bytes")
            
            # Preprocess the image and make prediction
            processed_image = preprocess_image(file_path)
            
            if processed_image is None:
                flash('Error processing image. Please try another image.')
                return redirect(url_for('index'))
                
            # Make prediction
            predictions = model.predict(processed_image)
            predicted_class_index = np.argmax(predictions[0])
            predicted_class = class_names[predicted_class_index]
            confidence = float(predictions[0][predicted_class_index] * 100)
            
            logger.info(f"Prediction: {predicted_class}, Confidence: {confidence}%")
            
            # Save scan to database
            save_scan(filename, predicted_class, confidence)
            
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            return render_template('result.html', 
                                  filename=filename, 
                                  prediction=predicted_class, 
                                  confidence=confidence,
                                  now=now)
        except Exception as e:
            logger.error(f"Error during upload and prediction: {str(e)}")
            logger.error(traceback.format_exc())
            flash('An error occurred during processing. Please try again.')
            return redirect(url_for('index'))
    else:
        flash('Allowed file types are png, jpg, jpeg')
        return redirect(url_for('index'))

@app.route('/about')
def about():
    """About page route"""
    return render_template('about.html')

@app.route('/dashboard')
def dashboard():
    """Dashboard page route with real data from database"""
    # Get real data from database
    recent_scans = get_recent_scans()
    stats = get_scan_statistics()
    
    return render_template('dashboard.html', recent_scans=recent_scans, stats=stats)

@app.route('/download-report/<filename>')
def download_report(filename):
    """Generate and download a PDF report for a scan"""
    try:
        # Get scan data
        scan_data = get_scan_by_filename(filename)
        
        if not scan_data:
            flash('Scan data not found.')
            return redirect(url_for('index'))
        
        # Image path - use absolute normalized path
        image_path = os.path.abspath(os.path.normpath(os.path.join(app.config['UPLOAD_FOLDER'], filename)))
        logger.info(f"Using image for PDF report: {image_path}")
        
        # Generate PDF
        pdf_buffer = generate_pdf_report(scan_data, image_path)
        
        if not pdf_buffer:
            flash('Error generating report.')
            return redirect(url_for('dashboard'))
        
        # Return PDF as a downloadable file
        report_filename = f"brain_tumor_report_{scan_data['id']}.pdf"
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=report_filename
        )
    except Exception as e:
        logger.error(f"Error downloading report: {str(e)}")
        logger.error(traceback.format_exc())
        flash('Error generating report.')
        return redirect(url_for('dashboard'))

@app.route('/export-csv')
def export_csv():
    """Export scan data as CSV"""
    try:
        # Generate CSV
        csv_buffer = generate_csv_export()
        
        if not csv_buffer:
            flash('Error generating CSV export.')
            return redirect(url_for('dashboard'))
        
        # Return CSV as a downloadable file
        export_filename = f"brain_tumor_scans_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            io.BytesIO(csv_buffer.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=export_filename
        )
    except Exception as e:
        logger.error(f"Error exporting CSV: {str(e)}")
        flash('Error generating CSV export.')
        return redirect(url_for('dashboard'))

@app.errorhandler(413)
def too_large(e):
    """Handle file too large error"""
    flash('File too large. Maximum size is 16MB.')
    return redirect(url_for('index'))

@app.errorhandler(404)
def page_not_found(e):
    """Handle 404 errors"""
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors"""
    logger.error(f"Server error: {str(e)}")
    return render_template('500.html'), 500

if __name__ == '__main__':
    # Create required directories
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize database
    init_db()
    
    # Check if model is loaded
    if model is None:
        print("WARNING: Model could not be loaded. Application will not function correctly.")
    
    app.run(debug=True) 