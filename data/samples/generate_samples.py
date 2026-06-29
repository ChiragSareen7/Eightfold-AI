"""Generate sample DOCX resumes for demo and tests."""

from pathlib import Path

from docx import Document


SAMPLES_DIR = Path(__file__).parent


def write_resume(filename: str, content: str) -> Path:
    path = SAMPLES_DIR / filename
    doc = Document()
    for line in content.strip().splitlines():
        doc.add_paragraph(line)
    doc.save(path)
    return path


JANE_RESUME = """
Jane Doe
Senior Software Engineer | Python & Cloud

jane.doe@example.com | +1 (415) 555-1234
San Francisco, CA
https://linkedin.com/in/janedoe
https://github.com/janedoe

Experience

Senior Software Engineer
Acme Corp
Jan 2018 - Present
Built scalable Python services on AWS.

Software Engineer
Beta LLC
Jun 2014 - Dec 2017
Developed React and Node.js applications.

Education

Stanford University
M.S. Computer Science
2014

Skills
Python, React, Node.js, AWS, Docker, Kubernetes
"""

JOHN_RESUME = """
Jonathan Smith
Product leader and strategist

john.smith@example.com | 415-555-9876
Oakland, CA

Experience

Product Manager
Globex Inc
2019 - Present
Led cross-functional product initiatives.

Education

UC Berkeley
MBA
2018

Skills
Product Management, Agile, SQL
"""

ALICE_RESUME = """
Alice Johnson
Data Scientist specializing in ML

alice.johnson@example.com | +44 20 7123 4567
London, United Kingdom

Experience

Data Scientist
Initech
Mar 2018 - Present
Built machine learning pipelines with Python and TensorFlow.

Education

Imperial College London
Ph.D. Statistics
2017

Skills
Python, Machine Learning, TensorFlow, SQL
"""


if __name__ == "__main__":
    write_resume("jane_doe.docx", JANE_RESUME)
    write_resume("john_smith.docx", JOHN_RESUME)
    write_resume("alice_johnson.docx", ALICE_RESUME)
    print("Sample resumes written to", SAMPLES_DIR)
