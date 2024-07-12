#!/usr/bin/env python
# coding: utf-8

# In[17]:


import pandas as pd
import geopandas as gpd
import plotly.express as px
import solara
from shapely.ops import unary_union

# Define file paths
admn_path = '../../shp/admn/col_admbnda_adm2_mgn_20200416.shp'
birds_path = '../../shp/birds/BIRD_Colombia/BIRD_Colombia.shp'
granjas_path = '../../shp/granjas/granjas/avestraspatio municipio.shp'
excel_path = "2024_06_21_Matriz IA.xlsx"

# Use pyogrio with Arrow for efficient file reading and filtering
admn_columns = ['ADM2_PCODE', 'ADM2_ES', 'geometry']
admn = gpd.read_file(admn_path, engine='pyogrio', use_arrow=True, columns=admn_columns)

birds_columns = ['Order_', 'Species', 'geometry']
birds = gpd.read_file(birds_path, engine='pyogrio', use_arrow=True, columns=birds_columns)

granjas_columns = ['MPIO_CDPMP', '2023_04__3', 'geometry']
granjas = gpd.read_file(granjas_path, engine='pyogrio', use_arrow=True, columns=granjas_columns)

# Simplify geometries to speed up processing
tolerance = 0.01  # Adjust tolerance as needed for your use case
try:
    admn['geometry'] = admn['geometry'].simplify(tolerance, preserve_topology=True)
    birds['geometry'] = birds['geometry'].simplify(tolerance, preserve_topology=True)
    granjas['geometry'] = granjas['geometry'].simplify(tolerance, preserve_topology=True)
except Exception as e:
    print(f"Error simplifying geometries: {e}")

# Calculate high backyard bird farming
umbral = 0.5
granjas['high_backyard_bird_farming'] = granjas['2023_04__3'] > umbral

# Filter bird species of interest
anseriformes_species = ['Anas acuta', 'Anas bahamensis', 'Anas crecca', 'Anas georgica',
                        'Anas strepera', 'Aythya affinis', 'Aythya collaris', 'Oxyura jamaicensis']
anf_birds = birds[(birds['Order_'] == 'Anseriformes') & (birds['Species'].isin(anseriformes_species))]

# Ensure CRS consistency
anf_birds = anf_birds.to_crs(admn.crs)

# Spatial joins with different suffixes
merged = gpd.sjoin(admn, granjas, how='left', predicate='intersects', lsuffix='admn', rsuffix='granjas')
merged = gpd.sjoin(merged, anf_birds, how='left', predicate='intersects', lsuffix='merged', rsuffix='anf_birds')

# Read Excel data and merge
new_data = pd.read_excel(excel_path, sheet_name='BD', header=1)
merged['ADM2_PCODE'] = merged['ADM2_PCODE'].str.replace('CO', '').astype(float)
merged = merged.merge(new_data, left_on='ADM2_PCODE', right_on='CMUN', how='left')

# Precompute static parts
merged['UniqueBirdSpeciesCount'] = merged.groupby('MUNI')['Species'].transform('nunique')

# Add a column for bird species presence in each municipality
merged['BirdSpecies'] = merged.groupby('ADM2_PCODE')['Species'].transform(lambda x: ', '.join(x.dropna().unique()))

# Function to assign weights based on selection
def assign_weights(order, weights):
    return {variable: weights[order.index(variable)] for variable in order}

# Solara component
@solara.component
def Page():
    variables_population = ['UniqueBirdSpeciesCount', 'high_backyard_bird_farming', 'TBRO', 'TVAC']
    labels_population = {
        'UniqueBirdSpeciesCount': 'Especie',
        'high_backyard_bird_farming': 'Proporción de aves de traspatio',
        'TBRO': 'Tasa de ocurrencia de brotes',
        'TVAC': 'Tasa de cobertura de vacunación en la población'
    }
    weights_population = [0.521, 0.271, 0.146, 0.062]

    variables_birds = ['UniqueBirdSpeciesCount', 'high_backyard_bird_farming', 'TBRO']
    labels_birds = {
        'UniqueBirdSpeciesCount': 'Especie',
        'high_backyard_bird_farming': 'Proporción de aves de traspatio',
        'TBRO': 'Tasa de ocurrencia de brotes'
    }
    weights_birds = [0.6110, 0.2780, 0.111]

    variables_bovinos = ['TBOV', 'UniqueBirdSpeciesCount', 'high_backyard_bird_farming', 'TBRO']
    labels_bovinos = {
        'TBOV': 'Proporción de población bovina',
        'UniqueBirdSpeciesCount': 'Especie',
        'high_backyard_bird_farming': 'Proporción de aves de traspatio',
        'TBRO': 'Tasa de ocurrencia de brotes'
    }
    weights_bovinos = [0.521, 0.271, 0.146, 0.062]

    order_inputs_population = {var: solara.use_state(str(i+1)) for i, var in enumerate(variables_population)}
    order_inputs_birds = {var: solara.use_state(str(i+1)) for i, var in enumerate(variables_birds)}
    order_inputs_bovinos = {var: solara.use_state(str(i+1)) for i, var in enumerate(variables_bovinos)}

    # State for holding the current figure
    current_fig_population, set_current_fig_population = solara.use_state(None)
    current_fig_birds, set_current_fig_birds = solara.use_state(None)
    current_fig_bovinos, set_current_fig_bovinos = solara.use_state(None)

    def plot_map(variables, order_inputs, weights):
        try:
            order = sorted(order_inputs.keys(), key=lambda x: int(order_inputs[x][0]))
            assigned_weights = assign_weights(order, weights)

            # Calculate Risk Score Index
            merged['RiskScoreIndex'] = sum(
                assigned_weights[var] * merged[var].astype(float) for var in variables
            )

            # Normalize the Risk Score Index
            min_score = merged['RiskScoreIndex'].min()
            max_score = merged['RiskScoreIndex'].max()
            merged['RiskScoreIndex'] = (merged['RiskScoreIndex'] - min_score) / (max_score - min_score)

            # Handle NaN and infinite values
            merged.replace([float('inf'), float('-inf')], float('nan'), inplace=True)
            merged.dropna(subset=['RiskScoreIndex'], inplace=True)

            # Remove duplicate municipalities for RiskScoreIndex
            merged_unique = merged.drop_duplicates(subset=['ADM2_PCODE'])

            # Plotting with Plotly
            fig = px.choropleth(
                merged_unique,
                geojson=merged_unique.__geo_interface__,
                locations=merged_unique.index,
                color="RiskScoreIndex",
                color_continuous_scale="RdPu",
                hover_name="ADM2_ES",
                hover_data={
                    "RiskScoreIndex": True,
                    "BirdSpecies": True,
                },
                range_color=(0, 1)  # Ensure the color scale range is set between 0 and 1
            )
            fig.update_geos(fitbounds="locations", visible=False)
            fig.update_layout(
                width=1900,  # Adjust the width for better rendering
                height=800,   # Adjust the height for better rendering
                coloraxis_colorbar=dict(title='Índice de riesgo')
            )
            return fig
        except Exception as e:
            print("Error plotting map:", e)
            return None

    def update_plot_population(*args):
        fig = plot_map(variables_population, order_inputs_population, weights_population)
        set_current_fig_population(fig)

    def update_plot_birds(*args):
        fig = plot_map(variables_birds, order_inputs_birds, weights_birds)
        set_current_fig_birds(fig)

    def update_plot_bovinos(*args):
        fig = plot_map(variables_bovinos, order_inputs_bovinos, weights_bovinos)
        set_current_fig_bovinos(fig)

    # Initial plot
    solara.use_effect(update_plot_population, [])
    solara.use_effect(update_plot_birds, [])
    solara.use_effect(update_plot_bovinos, [])

    with solara.AppBarTitle():
        solara.Text("Valoración del riesgo en tiempos de calma - Índice de riesgo influenza aviar H5N1")

    with solara.lab.Tabs():
        with solara.lab.Tab("Introducción"):
            solara.Markdown(r'''<center><h1>Estimación del riesgo por ocurrencia de brotes de influenza aviar (H5N1) en tiempos de calma</h1></center>
            <p style='text-align: justify;'>
            El objetivo de la evaluación de riesgo en tiempos de calma consiste en la identificación temprana de situaciones que pueden desencadenar la 
            ocurrencia de pandemias o emergencias de salud pública, causadas por agentes biológicos infecciosos de origen animal, pero también aquellas 
            originadas por otro tipo de agentes químicos o físicos, con el fin de facilitar la preparación para su atención oportuna, la contención del 
            riesgo a la salud humana y la minimización de sus efectos sobre la población.
            </p>
            <p style='text-align: justify;'>
            Para  identificar oportunamente este tipo de situaciones, es necesario evaluar el riesgo a la salud que suponen, para así, clasificarlas como 
            emergencias de proporciones similares a la de una pandemia o situaciones que requieran de la atención de las agencias y organismos nacionales e 
            internacionales para su control. La clasificación de esas situaciones tiene lugar mediante el uso de la metodología para la evaluación de riesgo,
            que identifica las señales y signos iniciales de la situación potencial de riesgo mediante la consulta de diversas fuentes de datos que se 
            consideren apropiadas en cada caso, su procesamiento a través del uso de un algoritmo de evaluación que tenga en cuenta los criterios de 
            priorización establecidos por expertos y. finalmente, la clasificación de la situación de riesgo de manera que se tomen decisiones oportunas 
            para la prevención y el control efectivo del riesgo en salud pública.
            </p>
            <p style='text-align: justify;'>
            En el caso de la influenza aviar (H5N1), se busca establecer qué zonas y municipios del país estarían en mayor riesgo de que ocurran brotes de
            la enfermedad en aves, bovinos y personas, con el fin de preparar oportunamente las medidas de vigilancia epidemiológica, de protección y control
            de la salud pública que brinden la mayor efectividad allí donde más impacto tendrán. Para ellos, se ha dispuesto de un *dashboard* que permite 
            describir cada escenario mediante la estimación de un índice de riesgo para cada municipio que se puede visualizar en un mapa interactivo, en el que
            además, es posible modificar la importancia de cada variable considerada para verificar el impacto que tiene sobre el resultado de la evaluación de 
            riesgo para cada escenario. Concretamente, se han considerado la presencia de aves migratorias, la proporción estimada de la población de aves de 
            traspatio, la tasa de ocurrencia de brotes de influenza aviar, la tasa de cobertura de vacunación de la población y la proporción de población 
            bovina en cada municipio para estimar el índice de riesgo. Ese índice se calcula conforme la metodología establecida por la Organización Mundial
            de la Salud (OMS) en su documento herramienta para la evaluación de riesgo pandémico de la influenza *"Tool for Influenza Pandemic Risk Assessment"* 
            (TIPRA), de 2016. 
            </p>
            <p style='text-align: justify;'>
            El resultado es el dashboard que se puede consultar a continuación, que fue construído empleando *Python* y que busca poner al alcance de los 
            evaluadores de riesgo una herramienta que permita identificar las regiones, municipios y poblaciones en mayor riesgo por la ocurrencia de brotes 
            de influenza aviar (H5N1) con el fin de que se pueda ejecutar cunado y desde donde se requiera, para disponer de elementos de juicio suficientes
            para preparar una respuesta oportuna y clara a una situación potencial de riesgo a la salud humana y facilitar así la toma de decisiones de 
            preparación y contención que se requieran en ese caso. Por supuesto, se trata de una herramienta modular que incorporará otros aspectos de la
            evaluación de riesgo y la protección de la salud pública en la medida en que se requiera. 
            </p>''')

        with solara.lab.Tab("BROTES EN AVES"):
            with solara.Row():
                for var in variables_birds:
                    solara.InputText(label=labels_birds[var], value=order_inputs_birds[var][0], on_value=order_inputs_birds[var][1], style={"width": "100px"})
                solara.Button(label="Generar mapa de riesgo", on_click=update_plot_birds)
            with solara.Row():
                solara.Text("En cada casilla, se puede ingresar el número que corresponda al orden de importancia que se le asigna a cada variable para la estimación del índice de riesgo. Posteriormente, se puede presionar el botón para generar mapa de riesgo y así obtener un nuevo mapa que refleje los cambios efectuados en la priorización de las variables.")
            with solara.Row(style={"min-height": "fit-content"}):
                    # Display the current figure if it exists
                    if current_fig_birds:
                        solara.FigurePlotly(current_fig_birds)

        with solara.lab.Tab("Brotes en bovinos"):
            with solara.Row():
                for var in variables_bovinos:
                    solara.InputText(label=labels_bovinos[var], value=order_inputs_bovinos[var][0], on_value=order_inputs_bovinos[var][1], style={"width": "100px"})
                solara.Button(label="Generar mapa de riesgo", on_click=update_plot_bovinos)
            with solara.Row():
                solara.Text("En cada casilla, se puede ingresar el número que corresponda al orden de importancia que se le asigna a cada variable para la estimación del índice de riesgo. Posteriormente, se puede presionar el botón para generar mapa de riesgo y así obtener un nuevo mapa que refleje los cambios efectuados en la priorización de las variables.")
            with solara.Row(style={"min-height": "fit-content"}):
                    # Display the current figure if it exists
                    if current_fig_bovinos:
                        solara.FigurePlotly(current_fig_bovinos)

        with solara.lab.Tab("Brotes en la población"):
            with solara.Row():
                for var in variables_population:
                    solara.InputText(label=labels_population[var], value=order_inputs_population[var][0], on_value=order_inputs_population[var][1], style={"width": "100px"})
                solara.Button(label="Generar mapa de riesgo", on_click=update_plot_population)
            with solara.Row():
                solara.Text("En cada casilla, se puede ingresar el número que corresponda al orden de importancia que se le asigna a cada variable para la estimación del índice de riesgo. Posteriormente, se puede presionar el botón para generar mapa de riesgo y así obtener un nuevo mapa que refleje los cambios efectuados en la priorización de las variables.")
            with solara.Row(style={"min-height": "fit-content"}):
                    # Display the current figure if it exists
                if current_fig_population:
                    solara.FigurePlotly(current_fig_population)

# Run the solara app
Page()

