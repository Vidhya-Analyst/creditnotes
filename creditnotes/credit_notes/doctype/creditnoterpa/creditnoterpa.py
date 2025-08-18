# Copyright (c) 2025, ASRN and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import datetime, timedelta
from creditnotes.credit_note import extract_fac_transactions


class CreditNoteRPA(Document):
	def autoname(self):
		if isinstance(self.month, str):
			self.month = datetime.strptime(self.month, "%Y-%m-%d").date()
		self.name = self.month.strftime('%Y %b')

	def validate(self):
		if isinstance(self.month, str):
			self.month = datetime.strptime(self.month, "%Y-%m-%d").date()
		start_date = self.month.replace(day=1)
		if self.month.month == 12:
			next_month = self.month.replace(year=self.month.year + 1, month=1, day=1)
		else:
			next_month = self.month.replace(month=self.month.month + 1, day=1)
		end_date = next_month - timedelta(days=1)

		if end_date < start_date:
			frappe.throw("End Date cannot be before Start Date")

	def on_submit(self):
		extract_fac_transactions(self)
		return

	def after_delete(self):
		frappe.db.sql(f"DELETE FROM `tabFacTransaction` WHERE parent_dates = '{self.name}'")
		return