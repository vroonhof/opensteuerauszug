import java.io.File;
import javax.xml.XMLConstants;
import javax.xml.transform.stream.StreamSource;
import javax.xml.validation.Schema;
import javax.xml.validation.SchemaFactory;
import javax.xml.validation.Validator;

public class XmlValidator {
    public static void main(String[] args) {
        if (args.length < 2) {
            System.out.println("Usage: java XmlValidator <xmlFilePath> <xsdFilePath>");
            return;
        }

        String xmlFilePath = args[0];
        String xsdFilePath = args[1];

        try {
            // 1. Create a SchemaFactory capable of understanding W3C XML Schema.
            SchemaFactory factory = SchemaFactory.newInstance(XMLConstants.W3C_XML_SCHEMA_NS_URI);

            // Set the error handler (optional, but good practice for custom error messages)
            // factory.setErrorHandler(new MyErrorHandler()); // You'd implement MyErrorHandler

            // 2. Load the schema.
            File schemaFile = new File(xsdFilePath);
            Schema schema = factory.newSchema(schemaFile);

            // 3. Create a validator for the schema.
            Validator validator = schema.newValidator();

            // Set the error handler for the validator (optional)
            // validator.setErrorHandler(new MyErrorHandler());

            // 4. Validate the XML instance.
            File xmlFile = new File(xmlFilePath);
            validator.validate(new StreamSource(xmlFile));

            System.out.println("XML document " + xmlFilePath + " is valid against " + xsdFilePath);

        } catch (Exception e) {
            System.err.println("Validation failed for " + xmlFilePath + ":");
            e.printStackTrace(); // Print full stack trace for debugging
            // For a production script, you might just print e.getMessage()
            System.exit(1); // Indicate failure
        }
    }
}
