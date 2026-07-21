This code develops a Research Intelligence platform on the CORDIS database, 
which is the European Union information system for projects funded in the European framework programmes.

Its goals are to help identify organisation partners for a given project proposal, 
and to explore the European research landscape.

Data are not provided, but can be downloaded from [here](https://cordis.europa.eu/projects), 
in the section "Download projects as open data".

## Features

### Filters and inputs
The platform provides a range of filters to help narrowing one's research. 
As shown in the screenshot below, the possible filters are: 
- **framework programme**: includes only the projects approved in the specified framework programmes;
- **country**: includes only the projects carried by organisations from the given countries;
- **organisation type**: includes only the projects where there were at least one organisation of the types specified
  public body, private company, research organisation, higher education establishment, other);
- **organisation name**: includes only the projects where the given organisations were involved;
- **topic**: filters out only the projects pertaining to the given topics (see [below](#custom-input));
- **custom input**: lets users insert a custom string to better narrow their interests (see [below](#topics));
- **coordinator**: retrieves only the projects for the given organisations where the aforementioned organisations coordinated them. 

<img width="1866" height="285" alt="Screenshot from 2026-07-21 14-11-38" src="https://github.com/user-attachments/assets/f2963dd4-f4a7-4604-abea-6f67e4b79823" />

#### Topics
Topics were found using BERTopic with HDBSCAN and Specter2 embedding model. For each project, the embedding was retrieved from its title and objective.
The found topics were afterwards organised in a 4 level taxonomy, using a Human-in-the-Loop approach and agglomerative clustering.
The resulting taxonomy is open for inspection in the Concept page.  

#### Custom input
The dashboard lets users define their own queries, in order to maximise usability and customisation. 
Some examples on what can be written here:
- users can search directly for a project title, objective or acronym (e.g. "ODEUROPA");
- users can ask for a certain category not found in the topic section, or difficult to define there (e.g. "disinformation in public speech");
- since the platform main goal is to help writing proposals, users can insert their whole proposal or project objective.

Given a custom input, the platform embeds it and search for the most similar projects. 
Internal tests discovered [BAAI's bge-m3 embedding model](https://huggingface.co/BAAI/bge-m3) suits this purpose the best.

### Results
Results are shown in three separate tabs. It is also possibile to download the .csv file of the results.

#### Tab "Project list"
<img width="1809" height="847" alt="Screenshot from 2026-07-21 14-35-33" src="https://github.com/user-attachments/assets/5b82f640-295c-4507-bf09-bf6ea016f54f" />

#### Tab "Aggregated view"
<img width="1803" height="852" alt="Screenshot from 2026-07-21 14-33-29" src="https://github.com/user-attachments/assets/b630d52b-482e-4b1f-b84d-3654f4694dc1" />

#### Tab "Latent space"
<img width="1801" height="850" alt="Screenshot from 2026-07-21 14-34-09" src="https://github.com/user-attachments/assets/7b63a5ee-ab34-4848-adbb-8b42c96c00e3" />
