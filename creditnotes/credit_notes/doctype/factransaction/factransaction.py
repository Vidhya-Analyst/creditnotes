# Copyright (c) 2025, ASRN and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FacTransaction(Document):
	def autoname(self):
		self.name = f"{self.document_ref}||{self.insurance_ref}"
		return













	





