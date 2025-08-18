# Copyright (c) 2025, Rohan Kumar Sahukar and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class FacTransaction_Reinsurer(Document):
	def autoname(self):
		self.name = f'{self.shortname} {self.ri_arrangement_line_id}'
		return
	
	@property
	def total_sum_insured(self):
		return self.sum_insured / self.this_share_percent * 100
	
	@property
	def total_premium(self):
		return self.premium_value + self.premium_tax
	
	@property
	def total_commission(self):
		return self.commission_value + self.commission_tax
	
	@property
	def net_due(self):
		return (self.premium_value + self.premium_tax) - (self.commission_value + self.commission_tax)
	
