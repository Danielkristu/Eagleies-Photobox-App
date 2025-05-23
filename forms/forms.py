# forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, IntegerField
from wtforms.validators import DataRequired, Length

class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=50)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=3, max=50)])


class ActivationForm(FlaskForm):
    activation_code = StringField("Kode Aktivasi", validators=[
        DataRequired(),
        Length(min=5, max=50, message="Kode aktivasi minimal 5 karakter")
    ])
    submit = SubmitField("Aktivasi")

class ManageUserForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=50)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=3, max=50)])
    price = IntegerField("Harga per Sesi", validators=[DataRequired()])
    xendit_api_key = StringField("Xendit API Key", validators=[DataRequired()])
    callback_url = StringField("Callback URL", validators=[DataRequired()])
    dslrbooth_api_url = StringField("DSLRBooth API URL", validators=[DataRequired()])
    dslrbooth_api_password = StringField("DSLRBooth API Password", validators=[DataRequired()])
    submit = SubmitField("Simpan")