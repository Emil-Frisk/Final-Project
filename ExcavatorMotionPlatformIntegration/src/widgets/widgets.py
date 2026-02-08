from PyQt6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout

class LabelButtonGroup(QWidget):
    def __init__(self, styles = None, visible=True, label_text="Label", button_text="Button", parent=None):
        super().__init__(parent)
        
        # Create layout for the group
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Create components
        self.label = QLabel(label_text)
        self.label.setWordWrap(True)
        self.button = QPushButton(button_text)
        if styles:
            self.button.setStyleSheet(styles["shutdown_btn"])
        
        # Add components to layout
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.button)
        
        # Set the layout
        self.setLayout(self.layout)
        self.setVisible(visible)

    # Convenience methods to access inner components
    def set_label_text(self, text):
        self.label.setText(text)
        
    def set_button_text(self, text):
        self.button.setText(text)
        
    def connect_button(self, function):
        self.button.clicked.connect(function)
    
    def toggle_visibility(self):
        self.setVisible(not self.isVisible())